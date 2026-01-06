"""SubFlow API"""

from fastapi import FastAPI
from redis.asyncio import Redis

from subflow.config import Settings
from routes.jobs import router as jobs_router

app = FastAPI(
    title="SubFlow API",
    description="Video Semantic Translation API",
    version="0.1.0",
)

settings = Settings()


@app.on_event("startup")
async def _startup() -> None:
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)


@app.on_event("shutdown")
async def _shutdown() -> None:
    redis: Redis | None = getattr(app.state, "redis", None)
    if redis is not None:
        await redis.aclose()


app.include_router(jobs_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
