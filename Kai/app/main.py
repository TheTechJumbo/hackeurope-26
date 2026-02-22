import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.activity import router as activity_router
from app.api.blocks import router as blocks_router
from app.api.chat import router as chat_router
from app.api.pipelines import router as pipelines_router
from app.api.webhooks import router as webhooks_router
from app.api.sse import router as sse_router
from app.api.websocket import router as websocket_router
from app.api.automation import router as automation_router
from app.blocks.loader import load_all_implementations
from app.config import settings
from app.engine.scheduler import rehydrate_schedules, shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading block implementations...")
    load_all_implementations()
    start_scheduler()
    rehydrate_schedules()
    logger.info("AgentFlow started.")
    yield
    logger.info("AgentFlow shutting down.")
    shutdown_scheduler()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(activity_router)
app.include_router(chat_router)
app.include_router(pipelines_router)
app.include_router(blocks_router)
app.include_router(webhooks_router)
app.include_router(sse_router)
app.include_router(websocket_router)
app.include_router(automation_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
