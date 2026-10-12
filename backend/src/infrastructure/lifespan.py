from src.core.db.session import SessionMaker
from src.infrastructure.redis import RedisBase
from src.settings import logger


async def startup(settings):
    SessionMaker.init(settings.db)
    RedisBase.init(settings.redis)


async def shutdown(settings):
    async def _shutdown(client):
        try:
            await client.close()
        except Exception as e:  # noqa: BLE001 - one client's shutdown failure must not block the rest
            logger.warning(f"Error occurred while closing {client}: {e}")

    await _shutdown(SessionMaker)
    await _shutdown(RedisBase)
