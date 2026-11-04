"""HTTP application entrypoint."""
import logging

from fastapi import FastAPI

from info_hub.health import router as health_router
from info_hub.settings import get_settings

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Feed & Research Platform",
    version="0.1.0",
    description="Phase 0: project foundation and runtime health checks.",
)
app.include_router(health_router)
