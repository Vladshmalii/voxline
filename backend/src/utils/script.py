"""Campaign call-script templating, sandboxed and resource-bounded.

A call script is a Jinja template written by an organization's operators and
rendered per attempt with three parameters: ``name`` (the client's), ``bonuses``
(list) and ``attributes`` (dict). Two protection layers, because Jinja's
sandbox stops security escapes but not resource exhaustion:

1. **In-environment caps** (this module): ``ImmutableSandboxedEnvironment``
   plus a capped ``range``, no ``namespace``/``cycler``/``lipsum`` globals
   (``namespace`` is what makes cross-iteration string doubling possible),
   the ``**`` operator blocked, size checks on ``*``/``+``, and a streamed
   render that aborts past an output cap. These give named, per-row errors.
2. **OS limits** (``validate_rows_limited``): upload-time validation renders
   every row strictly inside a disposable subprocess under CPU/memory
   rlimits, so even a template that evades layer 1 kills a child process,
   not the API or a worker carrying live calls.

Render timing: strict validation happens at campaign save (syntax) and at
upload (per row, real parameters). At call time the render is lenient —
missing values become empty strings — because refusing to talk to a customer
who already picked up is worse than a blank in the script.

Lives in ``utils`` deliberately: no project imports, so the validation
subprocess re-importing this module on spawn pulls in jinja2 and nothing
else — no settings, no ORM, no pipecat.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import datetime
from typing import Any

from jinja2 import StrictUndefined, TemplateSyntaxError, Undefined
from jinja2.sandbox import ImmutableSandboxedEnvironment, SecurityError

MAX_TEMPLATE_BYTES = 32 * 1024
MAX_OUTPUT_BYTES = 32 * 1024
MAX_RANGE_LENGTH = 1_000
#: Wall-clock budget for one lenient render at call time.
RENDER_TIMEOUT_SECONDS = 5.0
#: Budgets for the strict upload-time validation subprocess.
VALIDATE_CPU_SECONDS = 30
VALIDATE_MEMORY_BYTES = 512 * 1024 * 1024
VALIDATE_TIMEOUT_BASE_SECONDS = 10.0
VALIDATE_TIMEOUT_PER_ROW_SECONDS = 0.1


class ScriptError(ValueError):
    """A template that cannot be compiled or rendered; the message says why."""


def _capped_range(*args: int) -> range:
    result = range(*args)
    if len(result) > MAX_RANGE_LENGTH:
        raise SecurityError(
            f"range longer than {MAX_RANGE_LENGTH} is not allowed in call scripts"
        )
    return result


class _ScriptSandbox(ImmutableSandboxedEnvironment):
    """Sandbox with the resource-shaped operators reined in."""

    intercepted_binops = frozenset({"**", "*", "+"})

    def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
        if operator == "**":
            raise SecurityError("the ** operator is not allowed in call scripts")
        if operator == "*":
            for seq, times in ((left, right), (right, left)):
                if (
                    isinstance(seq, (str, list, tuple))
                    and isinstance(times, int)
                    and len(seq) * max(times, 0) > MAX_OUTPUT_BYTES
                ):
                    raise SecurityError("repetition result too large for a call script")
        if (
            operator == "+"
            and isinstance(left, str)
            and isinstance(right, str)
            and len(left) + len(right) > MAX_OUTPUT_BYTES
        ):
            raise SecurityError("string result too large for a call script")
        return super().call_binop(context, operator, left, right)


def _environment(strict: bool) -> _ScriptSandbox:
    env = _ScriptSandbox(
        undefined=StrictUndefined if strict else Undefined, autoescape=False
    )
    # Replace, not update: the defaults include namespace (cross-iteration
    # accumulation) and lipsum/cycler/joiner, none of which a script needs.
    env.globals = {"range": _capped_range}
    return env


def merge_player_attributes(
    attributes: dict[str, Any] | None,
    *,
    player_id: str | None = None,
    vip_status: str | None = None,
    last_deposit: float | None = None,
    last_active: datetime | None = None,
    country: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    structured = {
        "player_id": player_id,
        "vip_status": vip_status,
        "last_deposit": last_deposit,
        "last_active": last_active.isoformat() if last_active else None,
        "country": country,
        "timezone": timezone,
    }
    return {
        **(attributes or {}),
        **{k: v for k, v in structured.items() if v is not None},
    }


def render_script(
    source: str,
    *,
    name: str = "",
    bonuses: list[Any] | None = None,
    attributes: dict[str, Any] | None = None,
    strict: bool = False,
) -> str:
    """Render a call script with one call's parameters.

    Args:
        source: The Jinja template source.
        name: The client's name.
        bonuses: The offers available to this client.
        attributes: Per-call facts.
        strict: Fail on undefined variables (validation) instead of rendering
            them empty (call time).

    Returns:
        The rendered script, stripped.

    Raises:
        ScriptError: On oversize source, syntax errors, undefined variables
            (strict only), sandbox violations, or an over-cap output.
    """
    if len(source.encode()) > MAX_TEMPLATE_BYTES:
        raise ScriptError(f"template exceeds {MAX_TEMPLATE_BYTES} bytes")

    env = _environment(strict)
    try:
        template = env.from_string(source)
    except TemplateSyntaxError as exc:
        raise ScriptError(f"line {exc.lineno}: {exc.message}") from exc

    pieces: list[str] = []
    size = 0
    try:
        for piece in template.generate(
            name=name, bonuses=bonuses or [], attributes=attributes or {}
        ):
            size += len(piece)
            if size > MAX_OUTPUT_BYTES:
                raise ScriptError(f"rendered script exceeds {MAX_OUTPUT_BYTES} bytes")
            pieces.append(piece)
    except ScriptError:
        raise
    except Exception as exc:
        raise ScriptError(str(exc)) from exc
    return "".join(pieces).strip()


def validate_template(source: str) -> None:
    """Syntax-check a template without parameters (campaign save time).

    Raises:
        ScriptError: When the template does not compile or is oversize.
    """
    if len(source.encode()) > MAX_TEMPLATE_BYTES:
        raise ScriptError(f"template exceeds {MAX_TEMPLATE_BYTES} bytes")
    try:
        _environment(strict=True).from_string(source)
    except TemplateSyntaxError as exc:
        raise ScriptError(f"line {exc.lineno}: {exc.message}") from exc


async def render_script_async(
    source: str,
    *,
    name: str = "",
    bonuses: list[Any] | None = None,
    attributes: dict[str, Any] | None = None,
) -> str:
    """Lenient render off the event loop, for the call path.

    Raises:
        ScriptError: What ``render_script`` raises, plus a timeout.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                render_script, source, name=name, bonuses=bonuses, attributes=attributes
            ),
            timeout=RENDER_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise ScriptError(f"render exceeded {RENDER_TIMEOUT_SECONDS}s") from exc


def _limit_child_resources() -> None:
    """Executor initializer: cap the validation child's CPU and memory."""
    import resource

    for limit, value in (
        (resource.RLIMIT_CPU, VALIDATE_CPU_SECONDS),
        (resource.RLIMIT_AS, VALIDATE_MEMORY_BYTES),
    ):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):  # not enforceable on this platform (macOS AS)
            pass


def _validate_rows(source: str, rows: list[dict[str, Any]]) -> list[str | None]:
    """Strict-render every row; runs inside the limited child."""
    results: list[str | None] = []
    for row in rows:
        try:
            render_script(
                source,
                name=row.get("name", ""),
                bonuses=row.get("bonuses"),
                attributes=row.get("attributes"),
                strict=True,
            )
            results.append(None)
        except ScriptError as exc:
            results.append(str(exc))
    return results


async def validate_rows_limited(
    source: str, rows: list[dict[str, Any]]
) -> list[str | None]:
    """Strict-render every upload row in a resource-limited subprocess.

    Args:
        source: The campaign's template.
        rows: Per-row parameters (``name``, ``bonuses``, ``attributes``).

    Returns:
        One entry per row: None when it renders, else the error message.

    Raises:
        ScriptError: When rendering blows the subprocess's resource limits —
            the upload as a whole is refused, because a template that needs
            killing must not go near the call path.
    """
    if not rows:
        return []
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=1, initializer=_limit_child_resources
    )
    timeout = VALIDATE_TIMEOUT_BASE_SECONDS + VALIDATE_TIMEOUT_PER_ROW_SECONDS * len(
        rows
    )
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(executor, _validate_rows, source, rows),
            timeout=timeout,
        )
    except (TimeoutError, concurrent.futures.process.BrokenProcessPool) as exc:
        raise ScriptError("template validation exceeded resource limits") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
