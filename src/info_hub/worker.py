"""Durable RSS sync worker and basic subscription scheduler."""
import logging
import signal
import threading

from sqlalchemy.exc import SQLAlchemyError

from info_hub.services import (
    claim_next_run, process_run, queue_due_subscriptions, recover_abandoned_runs,
)
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
    logger.info("RSS worker started")
    while not shutdown.is_set():
        try:
            recover_abandoned_runs()
            queue_due_subscriptions()
            run_id = claim_next_run()
            if run_id is not None:
                process_run(run_id)
                continue
        except SQLAlchemyError:
            logger.exception("Worker database operation failed")
        shutdown.wait(3)
    logger.info("RSS worker stopped")


if __name__ == "__main__":
    main()
