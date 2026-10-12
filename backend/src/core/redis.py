import asyncio
from asyncio import Lock
from typing import Any, AsyncGenerator, Sequence

import orjson
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from redis.asyncio import Redis, Sentinel

from src.core.config import Config


class RedisBase:
    """Async Redis client singleton with namespaced key helpers.

    Provides get/set/delete, batch operations, distributed locking, and
    pub/sub on top of a shared `redis.asyncio.Redis` connection.

    Subclass and set `prefix` to add a class-level key segment:
    `<service>_<org_uuid>_<prefix>_<key>`.  Leave `prefix = None` to omit it.

    Call `open()` at startup and `close()` during shutdown.
    """

    prefix: str | None = None
    _client: Redis | None = None
    _sentinel: Sentinel | None = None
    _lock = asyncio.Lock()
    _settings: BaseSettings | None = None

    @classmethod
    def init(cls, settings: BaseSettings) -> None:
        """Initialize Redis settings from the application settings object.

        Must be called before the first `get_client()` call.
        """
        cls._settings = settings

    @classmethod
    async def get_client(cls) -> Redis:
        """Return the shared Redis client, creating it on first call.

        Uses an asyncio lock to prevent duplicate initialization.
        """
        if cls._settings is None:
            raise ValueError("Redis settings are not set")

        async with cls._lock:
            if cls._client is None:
                if cls._settings.type == "sentinel":
                    if cls._sentinel is None:
                        cls._sentinel = Sentinel(
                            cls._settings.sentinels,
                            sentinel_kwargs={"password": cls._settings.password},
                            password=cls._settings.password,
                        )
                    cls._client = cls._sentinel.master_for(cls._settings.service_name)
                else:
                    cls._client = Redis(
                        host=cls._settings.host,
                        port=cls._settings.port,
                        password=cls._settings.password,
                    )
        return cls._client

    @classmethod
    def key_factory(cls, org_uuid: str, key: str | bytes | int) -> str:
        """Build a namespaced Redis key.

        Format: `<service_prefix>_<org_uuid>[_<cls.prefix>]_<key>`
        """
        service_prefix = Config.get_service_prefix()
        if cls.prefix:
            return f"{{{service_prefix}:{org_uuid}}}:{cls.prefix}:{key}"
        return f"{{{service_prefix}:{org_uuid}}}:{key}"

    @classmethod
    async def get(cls, org_uuid: str, key: str | bytes | int) -> Any:
        """Fetch a single value and deserialize it from JSON.

        Returns `None` if the key does not exist.
        """
        client = await cls.get_client()
        bytes_data = await client.get(cls.key_factory(org_uuid, key))
        return orjson.loads(bytes_data) if bytes_data is not None else None

    @classmethod
    async def set(
        cls,
        org_uuid: str,
        key: str | bytes | int,
        value: Any,
        expire: int | None = 3600,
    ) -> None:
        """Serialize `value` to JSON and store it under the namespaced key.

        Args:
                expire: TTL in seconds.
        """
        client = await cls.get_client()
        await client.set(
            cls.key_factory(org_uuid, key), value_factory(value), ex=expire
        )

    @classmethod
    async def get_many(
        cls, org_uuid: str, keys: Sequence[str | bytes | int]
    ) -> list[Any]:
        """Fetch multiple keys in a single `MGET` call.

        Returns a list of deserialized values in the same order as `keys`.
        Missing keys are represented as `None`.
        """
        if not keys:
            return []
        client = await cls.get_client()
        bytes_data = await client.mget([cls.key_factory(org_uuid, key) for key in keys])
        return [orjson.loads(el) if el is not None else None for el in bytes_data]

    @classmethod
    async def set_many(
        cls,
        org_uuid: str,
        keys_values: dict[str | bytes | int, Any],
        expire: int | None = 3600,
    ) -> None:
        """Store multiple key-value pairs.

        Uses a pipeline when `expire` is set, otherwise falls back to
        `MSET` (which does not support per-key TTL).

        Args:
                expire: TTL in seconds applied to every key.  Pass `None` for
                        persistent storage via `MSET`.
        """
        if not keys_values:
            return
        if expire is None:
            client = await cls.get_client()
            await client.mset(
                {
                    cls.key_factory(org_uuid, key): value_factory(val)
                    for key, val in keys_values.items()
                }
            )
        else:
            client = await cls.get_client()
            async with client.pipeline(transaction=False) as pipeline:
                for key, val in keys_values.items():
                    pipeline.set(
                        cls.key_factory(org_uuid, key), value_factory(val), ex=expire
                    )
                await pipeline.execute()

    @classmethod
    async def delete_many(
        cls, org_uuid: str, keys: Sequence[str | bytes | int]
    ) -> None:
        """Delete one or more keys in a single `DEL` call."""
        if keys is None or isinstance(keys, list) and len(keys) == 0:
            return
        client = await cls.get_client()
        await client.delete(*[cls.key_factory(org_uuid, key) for key in keys])

    @classmethod
    async def lock(cls, org_uuid: str, key: str, **kwargs) -> Lock:
        """Return a Redis distributed lock for the given key.

        Defaults to a 30-second timeout if not provided via `kwargs`.
        The caller is responsible for acquiring and releasing the lock.
        """
        kwargs["timeout"] = kwargs.get("timeout") or 30
        client = await cls.get_client()
        return client.lock(cls.key_factory(org_uuid, key), **kwargs)

    @classmethod
    async def subscribe(cls, org_uuid: str, key: str) -> AsyncGenerator[Any, None]:
        """Async generator that yields deserialized messages from a pub/sub channel.

        Subscribes to the namespaced channel and yields each incoming message
        payload until the generator is canceled.  Unsubscribes and closes the
        pubsub connection in the `finally` block.
        """
        client = await cls.get_client()
        channel = cls.key_factory(org_uuid, key)
        pubsub = None
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message is None:
                    continue

                msg_type = message.get("type")
                if msg_type != "message":
                    continue

                yield message["data"]
        except asyncio.CancelledError:
            pass

        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                finally:
                    await pubsub.aclose()

    @classmethod
    async def publish(cls, org_uuid: str, key: str, message: Any) -> None:
        """Serialize `message` and publish it to the namespaced channel."""
        client = await cls.get_client()
        channel = cls.key_factory(org_uuid, key)
        await client.publish(channel, value_factory(message))

    @classmethod
    async def close(cls) -> None:
        """Close the Redis connection and reset the client singleton."""
        async with cls._lock:
            if cls._client is not None:
                await cls._client.close()
                cls._client = None
                cls._sentinel = None


def _default(val):
    """orjson fallback encoder: serializes Pydantic models to plain dicts."""
    if isinstance(val, BaseModel):
        return val.model_dump(mode="json")
    raise TypeError


def value_factory(value) -> bytes:
    """Serialize an arbitrary value to bytes for storage in Redis.

    Pydantic models are serialized via `model_dump_json` for speed.
    All other types are serialized with orjson (handles datetime, UUID, etc.).
    """
    if isinstance(value, BaseModel):
        return value.model_dump_json().encode("utf-8")

    return orjson.dumps(value, default=_default, option=orjson.OPT_NAIVE_UTC)


class PermissionCache(RedisBase):
    """Short-lived cache of resolved membership roles."""

    prefix = "perm"
