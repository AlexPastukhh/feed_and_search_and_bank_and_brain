"""HTTP application entrypoint."""
import logging

from fastapi import FastAPI

from info_hub.api import router as sources_router
from info_hub.health import router as health_router
from info_hub.search_api import router as search_router
from info_hub.settings import get_settings

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Feed & Research Platform",
    version="0.3.0",
    description="Source/subscription registry and first RSS ingestion slice.",
)
app.include_router(health_router)
app.include_router(sources_router)
app.include_router(search_router)
