"""SubFlow Worker"""

import asyncio
import json

from redis.asyncio import Redis

from subflow.config import Settings
from subflow.pipeline import PipelineExecutor, create_translation_pipeline
from handlers.job_handler import process_job


async def main():
    """Worker main entry point."""
    settings = Settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    pipeline: PipelineExecutor = create_translation_pipeline(settings)

    print("SubFlow Worker starting...")
    print(f"Redis: {settings.redis_url}")

    try:
        while True:
            item = await redis.brpop("subflow:jobs", timeout=5)
            if not item:
                continue
            _, raw = item
            payload = json.loads(raw)
            await process_job(payload, pipeline=pipeline, redis=redis, settings=settings)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
