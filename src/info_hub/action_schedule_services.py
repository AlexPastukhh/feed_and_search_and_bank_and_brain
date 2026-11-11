"""Opt-in fixed-interval Action scheduling, separate from immutable ActionVersions."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_broker import CapabilityBroker, ToolExecutionError
from info_hub.action_models import Action, utc_now
from info_hub.action_run_services import (
    RunConflict,
    RunNotFound,
    make_queued_action_run,
)
from info_hub.action_schedule_models import ActionSchedule
from info_hub.action_schedule_time import (
    MAX_INTERVAL_MINUTES,
    next_cadence_time,
)
from info_hub.action_workflow import WorkflowValidationError
from info_hub.db import open_session

logger = logging.getLogger(__name__)


class ScheduleIntervalRequired(ValueError):
    """No interval supplied, persisted or declared in the current Action."""


def schedule_summary(schedule: ActionSchedule | None, action_id: int) -> dict:
    if schedule is None:
        return {
            "action_id": action_id, "enabled": False, "every_minutes": None,
            "next_run_at": None, "last_enqueued_at": None,
            "last_skipped_at": None, "last_skip_reason": None,
            "updated_at": None,
        }
    return {
        "action_id": schedule.action_id,
        "enabled": schedule.enabled,
        "every_minutes": schedule.every_minutes,
        "next_run_at": schedule.next_run_at,
        "last_enqueued_at": schedule.last_enqueued_at,
        "last_skipped_at": schedule.last_skipped_at,
        "last_skip_reason": schedule.last_skip_reason,
        "updated_at": schedule.updated_at,
    }


def set_action_schedule(
    session: Session, *, action_id: int,
    enabled: bool, every_minutes: int | None = None,
    now: datetime | None = None, broker: CapabilityBroker | None = None,
) -> ActionSchedule | None:
    """Explicitly enable/disable. YAML declaration never activates a schedule."""
    action = session.scalar(
        select(Action).where(Action.id == action_id).with_for_update()
    )
    if action is None:
        raise RunNotFound("Action not found")
    schedule = session.scalar(
        select(ActionSchedule).where(ActionSchedule.action_id == action_id)
        .with_for_update()
    )
    if enabled and broker is not None:
        # Explicit opt-in must not activate an obviously unsupported workflow.
        from info_hub.action_services import get_action_version
        version = get_action_version(
            session, action_id=action.id,
            version_number=action.current_version_number,
        )
        if version is None:
            raise RunNotFound("Current Action version not found")
        broker.preflight(version.definition)

    interval = every_minutes
    if interval is None and schedule is not None:
        interval = schedule.every_minutes
    if interval is None and enabled:
        # YAML is only a default when user explicitly enables via PUT.
        from info_hub.action_services import get_action_version
        version = get_action_version(
            session, action_id=action.id,
            version_number=action.current_version_number,
        )
        if version is not None:
            declared = version.definition.get("schedule")
            if isinstance(declared, dict):
                interval = declared.get("every_minutes")
    if interval is None:
        if enabled:
            raise ScheduleIntervalRequired(
                "Provide every_minutes or declare schedule.every_minutes in Action YAML"
            )
        # Disabling an Action with no schedule is idempotent.
        session.commit()
        return None
    if type(interval) is not int or not 1 <= interval <= MAX_INTERVAL_MINUTES:
        raise ValueError("every_minutes must be an integer from 1 to 10080")

    instant = now or utc_now()
    if schedule is None:
        schedule = ActionSchedule(action_id=action_id, every_minutes=interval)
        session.add(schedule)
    schedule.every_minutes = interval
    schedule.enabled = enabled
    schedule.next_run_at = instant + timedelta(minutes=interval) if enabled else None
    schedule.last_skip_reason = None
    schedule.updated_at = instant
    session.commit()
    session.refresh(schedule)
    return schedule


def enqueue_due_action_schedules(
    broker: CapabilityBroker, *, now: datetime | None = None,
    max_schedules: int = 20,
) -> dict[str, int]:
    """One atomic enqueue per due schedule; never replay missed intervals.

    Manual launch and schedule changes lock Action first. Scheduler follows that
    order (Action, Schedule) to avoid deadlocks even with concurrent workers.
    """
    instant = now or utc_now()
    stats = {"queued": 0, "busy": 0, "invalid": 0}
    with open_session() as session:
        due = session.execute(
            select(ActionSchedule.id, ActionSchedule.action_id)
            .where(
                ActionSchedule.enabled.is_(True),
                ActionSchedule.next_run_at <= instant,
            )
            .order_by(ActionSchedule.next_run_at, ActionSchedule.id)
            .limit(max_schedules)
        ).all()

    for schedule_id, action_id in due:
        with open_session() as session:
            action = session.scalar(
                select(Action).where(Action.id == action_id).with_for_update()
            )
            if action is None:
                continue
            schedule = session.scalar(
                select(ActionSchedule).where(ActionSchedule.id == schedule_id)
                .with_for_update()
            )
            # Recheck after locks: a second worker or API may have changed it.
            if (
                schedule is None or not schedule.enabled
                or schedule.next_run_at is None or schedule.next_run_at > instant
            ):
                continue
            schedule.next_run_at = next_cadence_time(
                schedule.next_run_at,
                interval_minutes=schedule.every_minutes,
                now=instant,
            )
            schedule.updated_at = instant
            try:
                run = make_queued_action_run(
                    session, action=action, broker=broker, initiated_by="schedule",
                )
                session.flush()
                schedule.last_enqueued_at = instant
                schedule.last_skip_reason = None
                stats["queued"] += 1
                logger.info(
                    "Scheduled ActionRun %s for Action %s version %s",
                    run.id, action.id, action.current_version_number,
                )
            except RunConflict:
                schedule.last_skipped_at = instant
                schedule.last_skip_reason = "active_run"
                stats["busy"] += 1
            except (WorkflowValidationError, ToolExecutionError, RunNotFound) as exc:
                schedule.last_skipped_at = instant
                schedule.last_skip_reason = (
                    exc.code if isinstance(exc, ToolExecutionError) else "invalid_workflow"
                )
                stats["invalid"] += 1
                logger.warning(
                    "Skipped scheduled Action %s: %s",
                    action_id, schedule.last_skip_reason,
                )
            session.commit()
    return stats
