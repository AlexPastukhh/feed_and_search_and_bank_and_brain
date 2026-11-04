"""Standalone worker process, ready for durable jobs in a later phase.

Phase 0 intentionally does not poll or consume jobs. This process proves
that a separate runtime entrypoint can be deployed alongside the API.
"""
import logging
import signal
import threading

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from info_hub.db import get_engine
from info_hub.settings import get_settings

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
shutdown = threading.Event()


def request_shutdown(_signum: int, _frame: object) -> None:
    shutdown.set()


def main() -> None:
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    logger.info("Worker started (Phase 0: job processing not implemented)")
    while not shutdown.is_set():
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.debug("Database connectivity OK")
        except SQLAlchemyError:
            logger.warning("Worker database connectivity unavailable")
        shutdown.wait(30)
    logger.info("Worker shut down")


if __name__ == "__main__":
    main()
