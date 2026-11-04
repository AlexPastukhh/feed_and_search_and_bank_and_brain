"""Separate worker so waiting for Feedbrain never blocks its RSS ingestion worker."""
import logging
import signal
import threading

from sqlalchemy.exc import SQLAlchemyError

from info_hub.action_broker import configured_broker
from info_hub.action_schedule_services import enqueue_due_action_schedules
from info_hub.action_run_services import (
    claim_next_action_run, process_action_run, recover_abandoned_action_runs,
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
    broker = configured_broker()
    logger.info("Action worker started (capabilities=%s)", sorted(broker.capabilities))
    while not shutdown.is_set():
        try:
            recovered = recover_abandoned_action_runs()
            if recovered:
                logger.warning("Marked %d stale ActionRuns as interrupted", recovered)
            schedule_stats = enqueue_due_action_schedules(broker)
            if schedule_stats["busy"] or schedule_stats["invalid"]:
                logger.info("Action scheduler: %s", schedule_stats)
            run_id = claim_next_action_run()
            if run_id is not None:
                process_action_run(run_id, broker)
                continue
        except SQLAlchemyError:
            logger.exception("Action worker database operation failed")
        except Exception:
            logger.exception("Action worker unexpected error; no automatic replay")
        shutdown.wait(3)
    logger.info("Action worker stopped")


if __name__ == "__main__":
    main()
