"""The call-script sandbox: what renders, what is refused, what is capped.

Lives in the api suite for its interpreter (no DB use): these are pure-python
checks of ``utils/script.py``.
"""

from __future__ import annotations

import pytest

from src.utils.script import (
    MAX_OUTPUT_BYTES,
    ScriptError,
    render_script,
    render_script_async,
    validate_rows_limited,
    validate_template,
)


def test_renders_the_three_parameters():
    script = render_script(
        "Hi {{ name }}. {% for b in bonuses %}Offer {{ b.code }}. {% endfor %}"
        "VIP: {{ attributes.vip }}.",
        name="Anna",
        bonuses=[{"code": "WB50"}, {"code": "FS20"}],
        attributes={"vip": "yes"},
    )
    assert script == "Hi Anna. Offer WB50. Offer FS20. VIP: yes."


def test_strict_flags_missing_values_lenient_renders_them_empty():
    with pytest.raises(ScriptError, match="undefined"):
        render_script("Offer {{ promo_code }}.", strict=True)
    with pytest.raises(ScriptError, match="element"):  # empty bonuses, indexed anyway
        render_script("Offer {{ bonuses[0].code }}.", strict=True)
    # Call time is lenient: a blank beats refusing to talk to someone who answered.
    assert render_script("Offer {{ promo_code }}!") == "Offer !"


def test_validate_template_names_the_broken_line():
    with pytest.raises(ScriptError, match="line 2"):
        validate_template("fine\n{% for %}")


@pytest.mark.parametrize(
    "source",
    [
        "{{ 10 ** 9 }}",  # power operator blocked outright
        "{{ 'x' * 10**6 }}",  # power inside still blocked
        "{{ 'x' * 999999999 }}",  # sequence repetition over the output cap
        "{% for i in range(10**9) %}x{% endfor %}",  # unbounded loop
        "{% for i in range(2000) %}x{% endfor %}",  # over the range cap
    ],
)
def test_resource_shaped_operations_are_refused(source):
    with pytest.raises(ScriptError):
        render_script(source, strict=True)


def test_output_and_template_size_caps():
    with pytest.raises(ScriptError, match="exceeds"):
        render_script("{% for i in range(1000) %}" + "y" * 100 + "{% endfor %}")
    with pytest.raises(ScriptError, match="exceeds"):
        validate_template("x" * (MAX_OUTPUT_BYTES + 1))


def test_namespace_is_not_available():
    # namespace() is what makes cross-iteration string doubling possible —
    # its absence is a guarantee, not an accident.
    with pytest.raises(ScriptError):
        render_script("{% set ns = namespace(x='a') %}", strict=True)


async def test_async_render_matches_sync():
    assert await render_script_async("Hi {{ name }}", name="Ben") == "Hi Ben"


async def test_validate_rows_limited_gives_per_row_verdicts():
    results = await validate_rows_limited(
        "Offer {{ bonuses[0].code }} to {{ name }}.",
        [
            {"name": "Anna", "bonuses": [{"code": "WB50"}], "attributes": {}},
            {"name": "Ben", "bonuses": [], "attributes": {}},
        ],
    )
    assert results[0] is None
    assert results[1] is not None and "element" in results[1]
