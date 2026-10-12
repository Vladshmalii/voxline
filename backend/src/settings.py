import enum
import hashlib
import hmac
import sys
from contextvars import ContextVar
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.config import Config


class ApplicationState(str, enum.Enum):
    """Application state enum."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"

    @property
    def is_production(self):
        return self == ApplicationState.PRODUCTION


class DBSettings(BaseSettings):
    """Postgres settings class."""

    host: str
    port: int
    user: str
    password: str
    prefix: str = "org_"
    #: The control database: users, organizations, memberships, refresh tokens.
    control_name: str = "voxline_control"

    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 1800
    pool_pre_ping: bool = True

    @property
    def url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}"
        )


class RedisSettings(BaseSettings):
    """Redis settings class."""

    type: Literal["standalone"]
    host: str
    port: int
    password: str

    @property
    def url(self) -> str:
        return f"redis://:{self.password}@{self.host}:{self.port}/0"


class RedisSentinelSettings(BaseSettings):
    """Redis Sentinel settings class."""

    type: Literal["sentinel"]
    sentinels: list[tuple[str, int]]
    service_name: str
    password: str


class CallWorkerSettings(BaseSettings):
    """The call dispatcher: how calls are claimed, dialed, and paced.

    ``media_url`` is the default public base the telephony provider connects
    back to (``wss://…`` — Twilio refuses anything unencrypted); it points at
    the *hooks* service, which owns the media sockets. A telephony row can
    override it via ``options.media_url_base``, which is how the VPC-local
    jambonz bridge gets a private URL while Twilio gets the public one.
    """

    media_url: str
    #: Calls in flight (dialing + in progress) across the platform; dial tasks
    #: stop claiming at the cap. Sized to trunk CPS and GPU capacity, not to
    #: any process — pipelines run in the hooks service. Measured from the
    #: registry's TTL'd keys, so it cannot drift after a crash.
    max_concurrent_calls: int = 10
    #: New dials one dispatcher tick (one minute) may start, on top of the
    #: concurrency cap — the campaign pacer.
    max_dials_per_minute: int = 30
    #: How long a dialed call may wait for its media socket before it is failed.
    dial_timeout_seconds: int = 60
    #: A call in progress longer than this is presumed leaked and swept failed.
    max_call_seconds: int = 7200


class LeadsSettings(BaseSettings):
    """Where "request a demo" submissions from the landing page are delivered.

    A Telegram bot token and the chat that should receive the requests. Unset
    (``None`` on :class:`Settings`) the public ``/v1/leads`` route answers 503.
    """

    bot_token: str
    chat_id: str


class JWTSettings(BaseSettings):
    """Session tokens: a short-lived HS256 access JWT plus an opaque refresh token.

    ``secret`` defaults to a key derived from ``SECRET_KEY`` (see
    ``Settings._derive_jwt_secret``); set ``JWT__SECRET`` to override it.
    """

    secret: str = ""
    algorithm: str = "HS256"
    access_ttl_seconds: int = 15 * 60
    refresh_ttl_days: int = 30
    #: None = secure cookies in production only.
    cookie_secure: bool | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None


class Settings(BaseSettings):
    """Settings class."""

    # application
    secret_key: str
    service_prefix: str
    log_level: str = "INFO"
    #: Fail-safe default: a deploy that forgets APPLICATION_STATE runs hardened,
    #: not with debug tracebacks and non-Secure cookies.
    application_state: ApplicationState = ApplicationState.PRODUCTION
    #: Space-separated allowed origins. Empty = no cross-origin access; "*" is
    #: refused in production because the API authenticates with cookies.
    origins: str = ""
    #: Rows one SMS/call history export may hold before it is refused with
    #: "narrow the filters" — kept under Excel's 1,048,576-row sheet limit.
    export_max_rows: int = 200_000

    # infrastructure
    db: DBSettings
    redis: Annotated[RedisSettings | RedisSentinelSettings, Field(discriminator="type")]
    call_worker: CallWorkerSettings | None = None
    leads: LeadsSettings | None = None

    jwt: JWTSettings = Field(default_factory=JWTSettings)

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> "Settings":
        if not self.application_state.is_production:
            return self
        if self.secret_key.startswith("change-me") or len(self.secret_key) < 32:
            raise ValueError(
                "SECRET_KEY is a placeholder or shorter than 32 characters; "
                "set a long random value"
            )
        if "*" in self.origins.split():
            raise ValueError("ORIGINS may not be * in production")
        return self

    @model_validator(mode="after")
    def _derive_jwt_secret(self) -> "Settings":
        """Session-token key: ``JWT__SECRET`` if given, else HMAC(SECRET_KEY)."""
        if not self.jwt.secret:
            self.jwt.secret = hmac.new(
                self.secret_key.encode(), b"voxline-jwt-v1", hashlib.sha256
            ).hexdigest()
        if self.jwt.cookie_secure is None:
            self.jwt.cookie_secure = self.application_state.is_production
        return self

    # extra='ignore': the .env also carries process-manager knobs consumed by
    # the launch scripts (APP_WORKERS_NUM, HOOKS_PORT…), not by Settings —
    # newer pydantic-settings forbids unknown dotenv keys by default.
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def patch_record(record):
    try:
        ctx = log_context.get()
    except LookupError:
        ctx = {}

    if ctx:
        record["extra"].update(ctx)
    return record


SETTINGS = Settings()
Config.init(
    SETTINGS.service_prefix, not SETTINGS.application_state.is_production, SETTINGS.jwt
)

log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default=None)
logger.remove()
logger.add(sys.stdout, level=SETTINGS.log_level, serialize=True)
logger = logger.patch(patch_record)
