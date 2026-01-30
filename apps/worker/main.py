"""SubFlow Worker"""

import asyncio
import json
import logging

from redis.asyncio import Redis

from subflow.config import Settings
from subflow.services.llm_health import init_llm_health_monitor
from subflow.utils.logging_setup import setup_logging
from handlers.project_handler import process_project_task
from recovery import recover_orphan_projects


async def main():
    """Worker main entry point."""
    settings = Settings()
    setup_logging(settings)
    logger = logging.getLogger("subflow.worker")
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    init_llm_health_monitor(redis=redis)

    logger.info("Worker starting (redis=%s)", settings.redis_url)

    try:
        try:
            recovered = await recover_orphan_projects(settings=settings)
            if recovered:
                logger.info("startup recovery completed (recovered=%d)", recovered)
        except Exception:
            logger.exception("startup recovery failed")

        while True:
            item = await redis.brpop("subflow:projects:queue", timeout=5)
            if not item:
                continue
            _, raw = item
            payload = json.loads(raw)
            await process_project_task(payload, redis=redis, settings=settings)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
