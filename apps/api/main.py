"""SubFlow API"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from subflow.config import Settings
from subflow.repositories import DatabasePool
from subflow.services.llm_health import init_llm_health_monitor
from routes.health import router as health_router
from routes.projects import router as projects_router
from routes.uploads import router as uploads_router
from subflow.utils.logging_setup import setup_logging

settings = Settings()
setup_logging(settings)
logger = logging.getLogger("subflow.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.settings = settings
    app.state.db_pool = await DatabasePool.get_pool(settings)
    init_llm_health_monitor(redis=app.state.redis)
    logger.info("API starting (redis=%s)", settings.redis_url)
    try:
        yield
    finally:
        redis: Redis | None = getattr(app.state, "redis", None)
        if redis is not None:
            await redis.aclose()
        await DatabasePool.close()


app = FastAPI(
    title="SubFlow API",
    description="Video Semantic Translation API",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(projects_router)
app.include_router(uploads_router)
app.include_router(health_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
