"""The task queue's broker — taskiq over Redis (standalone or Sentinel).

Replaces the previous ``taskiq_pg`` (Postgres LISTEN/NOTIFY) broker: this
service's Postgres is only reachable through PgBouncer in transaction-pooling
mode, which silently drops LISTEN/NOTIFY — PgBouncer detaches the backend
connection between transactions, so a NOTIFY the server sends after that
point arrives at a connection nobody is listening on anymore and gets logged
as a warning, never delivered. Redis has no such pooler-vs-pubsub conflict.

``SETTINGS.redis`` already discriminates standalone vs Sentinel (the same
config the Redis wrapper itself understands) — this module picks the matching
taskiq-redis broker/result-backend pair from that one setting, so an operator
switches topology by changing ``REDIS__TYPE`` in env, no code change.

Redis Stream + consumer groups (``RedisStreamBroker`` / Sentinel variant) is
used rather than the simpler list-queue broker: a stream gives at-least-once
delivery (unacked messages are redelivered after ``idle_timeout``), which
turns a worker crash mid-dial into a retry instead of a silently lost call.
This is safe here because ``dial_call``'s claim is a guarded
``queued -> dialing`` UPDATE (see ``tasks.py``) — a duplicate delivery finds
the row already claimed and simply no-ops, so redelivery never double-dials.

The queue is namespaced by ``SETTINGS.service_prefix`` in case this Redis is
ever shared with another service, mirroring the previous broker's
schema/channel namespacing for the same reason.
"""

from __future__ import annotations

from loguru import logger
from taskiq import AsyncBroker
from taskiq_redis import (
    RedisAsyncResultBackend,
    RedisAsyncSentinelResultBackend,
    RedisStreamBroker,
    RedisStreamSentinelBroker,
)

from src.settings import SETTINGS, RedisSentinelSettings

#: Consumer-group block time for XREADGROUP. Redis returns an empty response
#: (not an error) once this elapses with no new messages, so the client's
#: blocking read is bounded by this, not by how long the queue stays idle.
_XREAD_BLOCK_MS = 10_000
#: redis-py >=8 defaults a connection's own read timeout to 5s, well under
#: how long a blocking XREADGROUP can legitimately wait (_XREAD_BLOCK_MS).
#: Left at the default, every idle poll longer than 5s raises a client-side
#: timeout and restarts the worker — a crash-loop where no task is ever
#: consumed while the scheduler keeps enqueuing them. Pinned above
#: _XREAD_BLOCK_MS with margin so a real empty-response round trip never
#: trips it.
_SOCKET_TIMEOUT_S = 30.0
_RESULT_TTL_SECONDS = 3600
#: Approximate cap on stream length (``XADD ... MAXLEN ~``). Acked entries
#: aren't removed from a Redis stream on their own — without a cap this grows
#: forever. There's no equivalent of the old Postgres broker's hourly purge
#: task here; trimming is the broker's own job, done inline on every kick.
_STREAM_MAXLEN = 10_000


def make_broker() -> AsyncBroker:
    """Build the service's broker from ``SETTINGS.redis``."""
    redis = SETTINGS.redis
    queue_name = f"{SETTINGS.service_prefix}_taskiq"

    if isinstance(redis, RedisSentinelSettings):
        sentinels = list(redis.sentinels)
        auth = {"password": redis.password} if redis.password else {}
        # The master connection holds the blocking read, so it gets the long
        # timeout; a sentinel round trip is quick, so an unhealthy sentinel
        # is skipped instead of stalling the whole connect.
        conn_kwargs = {"socket_timeout": _SOCKET_TIMEOUT_S, **auth}
        sentinel_kwargs = {"socket_timeout": 5.0, **auth}
        logger.info(
            f"broker config: Redis Sentinel master={redis.service_name!r} "
            f"sentinels={sentinels} queue={queue_name!r} "
            f"socket_timeout={_SOCKET_TIMEOUT_S}s xread_block={_XREAD_BLOCK_MS}ms"
        )
        result_backend = RedisAsyncSentinelResultBackend(
            sentinels=sentinels,
            master_name=redis.service_name,
            result_ex_time=_RESULT_TTL_SECONDS,
            sentinel_kwargs=sentinel_kwargs,
            **conn_kwargs,
        )
        broker: AsyncBroker = RedisStreamSentinelBroker(
            sentinels=sentinels,
            master_name=redis.service_name,
            queue_name=queue_name,
            xread_block=_XREAD_BLOCK_MS,
            maxlen=_STREAM_MAXLEN,
            sentinel_kwargs=sentinel_kwargs,
            **conn_kwargs,
        )
    else:
        logger.info(
            f"broker config: Redis standalone host={redis.host}:{redis.port} "
            f"queue={queue_name!r} socket_timeout={_SOCKET_TIMEOUT_S}s "
            f"xread_block={_XREAD_BLOCK_MS}ms"
        )
        result_backend = RedisAsyncResultBackend(
            redis_url=redis.url,
            result_ex_time=_RESULT_TTL_SECONDS,
        )
        broker = RedisStreamBroker(
            url=redis.url,
            queue_name=queue_name,
            xread_block=_XREAD_BLOCK_MS,
            maxlen=_STREAM_MAXLEN,
            socket_timeout=_SOCKET_TIMEOUT_S,
        )

    return broker.with_result_backend(result_backend)
