"""Dedicated, narrow Action Core ASGI app for direct HTTPS/443 admission.

The owner starts this app in its own TLS-enabled Uvicorn process; the
legacy local HTTP app never mounts its Gateway routes. No proxy or fallback.
"""
from fastapi import FastAPI

from info_hub.gateway_action_api import router as gateway_action_router

app = FastAPI(
    title="Action Core Gateway READ",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
)
app.include_router(gateway_action_router)
