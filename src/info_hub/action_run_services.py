"""Queue and execute version-pinned Actions with durable per-step results."""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_broker import (
    CapabilityBroker, ToolExecutionError, safe_error_code,
    safe_error_external_ref, safe_error_message,
)
from info_hub.action_models import Action, ActionVersion, utc_now
from info_hub.action_run_models import ActionResult, ActionRun, ActionStepRun
from info_hub.action_services import get_action_version
from info_hub.action_workflow import WorkflowValidationError
from info_hub.db import open_session

logger = logging.getLogger(__name__)

# A workflow has at most 24 steps; each Feedbrain step has a 120s deadline.
# A stale job is marked interrupted, never automatically replayed.
ABANDONED_AFTER = timedelta(hours=2)


class RunConflict(ValueError):
    """An Action already has a queued/running execution."""


class RunNotFound(LookupError):
    """An Action or requested immutable version does not exist."""


def make_queued_action_run(
    session: Session, *, action: Action, broker: CapabilityBroker,
    version_number: int | None = None, initiated_by: str = "api",
) -> ActionRun:
    """Caller holds a row lock on Action; transaction is committed by caller.

    Shared by manual API and scheduler to enforce one active run per Action.
    """
    number = action.current_version_number if version_number is None else version_number
    version = get_action_version(session, action_id=action.id, version_number=number)
    if version is None:
        raise RunNotFound("Action version not found")
    broker.preflight(version.definition)
    active = session.scalar(
        select(ActionRun.id).where(
            ActionRun.action_id == action.id,
            ActionRun.status.in_(("queued", "running")),
        ).limit(1)
    )
    if active is not None:
        raise RunConflict("Action already has an active execution")
    run = ActionRun(
        action_id=action.id, action_version_id=version.id,
        initiated_by=initiated_by, status="queued",
    )
    session.add(run)
    return run


def queue_action_run(
    session: Session, *, action_id: int, broker: CapabilityBroker,
    version_number: int | None = None, initiated_by: str = "api",
) -> ActionRun:
    """Atomically pin a version and prevent parallel executions of one Action."""
    action = session.scalar(select(Action).where(Action.id == action_id).with_for_update())
    if action is None:
        raise RunNotFound("Action not found")
    run = make_queued_action_run(
        session, action=action, broker=broker,
        version_number=version_number, initiated_by=initiated_by,
    )
    session.commit()
    session.refresh(run)
    return run


def claim_next_action_run() -> int | None:
    """PostgreSQL SKIP LOCKED: each queued run is claimed by only one worker."""
    with open_session() as session:
        run = session.scalar(
            select(ActionRun).where(ActionRun.status == "queued")
            .order_by(ActionRun.id).limit(1).with_for_update(skip_locked=True)
        )
        if run is None:
            return None
        run.status = "running"
        run.started_at = utc_now()
        session.commit()
        return run.id


def _create_step(run_id: int, step: dict, tool: str) -> int:
    with open_session() as session:
        record = ActionStepRun(
            action_run_id=run_id, step_id=step["id"],
            capability=step["capability"], status="running", tool=tool,
        )
        session.add(record)
        session.commit()
        return record.id


def _record_external_ref(step_row_id: int, external_ref: str) -> None:
    """Persist the accepted external job before polling it for a terminal state."""
    with open_session() as session:
        step = session.get(ActionStepRun, step_row_id)
        if step is None or step.status != "running":
            raise RuntimeError("Action step is no longer running")
        step.external_run_ref = external_ref
        session.commit()


def _end_step(
    step_row_id: int, *, status: str, tool: str | None = None,
    external_run_ref: str | None = None, details: dict | None = None,
    error_code: str | None = None, error_message: str | None = None,
) -> None:
    with open_session() as session:
        step = session.get(ActionStepRun, step_row_id)
        if step is None or step.status != "running":
            raise RuntimeError("Action step state was lost")
        step.status = status
        if tool is not None:
            step.tool = tool
        if external_run_ref is not None:
            step.external_run_ref = external_run_ref
        step.details = details or {}
        step.error_code = error_code
        step.error_message = error_message
        step.finished_at = utc_now()
        session.commit()


def _finalize_run(
    run_id: int, *, status: str, error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    with open_session() as session:
        run = session.get(ActionRun, run_id)
        if run is None or run.status != "running":
            raise RuntimeError("Action run is no longer running")
        steps = session.scalars(
            select(ActionStepRun).where(ActionStepRun.action_run_id == run_id)
            .order_by(ActionStepRun.id)
        ).all()
        details = {
            "steps": [{
                "step_id": step.step_id, "capability": step.capability,
                "tool": step.tool, "status": step.status,
                "external_run_ref": step.external_run_ref,
                "details": step.details, "error_code": step.error_code,
            } for step in steps],
        }
        summary = (
            f"Completed {len(steps)} step(s)"
            if status == "completed"
            else f"Execution {status}: {error_code or 'unknown_error'}"
        )
        run.status = status
        run.error_code = error_code
        run.error_message = error_message
        run.finished_at = utc_now()
        session.add(ActionResult(
            action_run_id=run.id, status=status, summary=summary, details=details,
        ))
        session.commit()


def _fail_run(run_id: int, code: str, message: str) -> None:
    _finalize_run(
        run_id, status="failed", error_code=code, error_message=message,
    )


def process_action_run(run_id: int, broker: CapabilityBroker) -> None:
    """Execute an already-claimed run, committing each step around external HTTP."""
    with open_session() as session:
        run = session.get(ActionRun, run_id)
        if run is None or run.status != "running":
            raise RuntimeError("Only claimed ActionRuns can be processed")
        version = session.get(ActionVersion, run.action_version_id)
        if version is None or version.action_id != run.action_id:
            raise RuntimeError("ActionRun references an invalid ActionVersion")
        definition = version.definition

    try:
        steps = broker.preflight(definition)
    except (ToolExecutionError, WorkflowValidationError) as exc:
        code = (
            safe_error_code(exc.code)
            if isinstance(exc, ToolExecutionError) else "invalid_workflow"
        )
        _fail_run(run_id, code, safe_error_message(str(exc)))
        return
    except Exception:
        logger.exception("Unexpected Action preflight failure for run %s", run_id)
        _fail_run(run_id, "unexpected_error", "Unexpected Action preflight failure")
        return

    for step in steps:
        step_row_id = _create_step(
            run_id, step, broker.tool_name_for(step),
        )  # durable before external side effects
        try:
            outcome = broker.dispatch_step(
                step,
                on_external_ref=lambda ref: _record_external_ref(step_row_id, ref),
            )
        except ToolExecutionError as exc:
            # An adapter's error path must not bypass the successful-result
            # reference validation or leak credential-looking error text.
            code = safe_error_code(exc.code)
            message = safe_error_message(str(exc))
            external_ref = safe_error_external_ref(exc.external_run_ref, step["tool"])
            _end_step(
                step_row_id, status="failed", tool=step["tool"],
                external_run_ref=external_ref, error_code=code,
                error_message=message,
            )
            _fail_run(run_id, code, message)
            return
        except (WorkflowValidationError, ValueError):
            _end_step(
                step_row_id, status="failed", error_code="invalid_step",
                error_message="Step is not executable",
            )
            _fail_run(run_id, "invalid_step", "Step is not executable")
            return
        except Exception:
            logger.exception("Unexpected step error in ActionRun %s", run_id)
            _end_step(
                step_row_id, status="failed", error_code="unexpected_error",
                error_message="Unexpected tool execution failure",
            )
            _fail_run(run_id, "unexpected_error", "Unexpected tool execution failure")
            return
        _end_step(
            step_row_id, status="completed", tool=outcome.tool,
            external_run_ref=outcome.external_run_ref, details=outcome.details,
        )
    _finalize_run(run_id, status="completed")


def recover_abandoned_action_runs() -> int:
    """Do not blindly replay ambiguous HTTP writes after worker crashes."""
    cutoff = utc_now() - ABANDONED_AFTER
    with open_session() as session:
        abandoned = session.scalars(
            select(ActionRun).where(
                ActionRun.status == "running", ActionRun.started_at < cutoff,
            )
            .order_by(ActionRun.id).limit(20).with_for_update(skip_locked=True)
        ).all()
        for run in abandoned:
            step_records = session.scalars(
                select(ActionStepRun).where(
                    ActionStepRun.action_run_id == run.id,
                    ActionStepRun.status == "running",
                )
            ).all()
            for step in step_records:
                step.status = "interrupted"
                step.finished_at = utc_now()
                step.error_code = "worker_interrupted"
                step.error_message = "Worker interrupted; external outcome may be unknown"
            run.status = "interrupted"
            run.finished_at = utc_now()
            run.error_code = "worker_interrupted"
            run.error_message = "Worker interrupted; external outcome may be unknown"
            session.add(ActionResult(
                action_run_id=run.id, status="interrupted",
                summary="Execution interrupted; no automatic retry",
                details={"external_outcome": "may_be_unknown"},
            ))
        session.commit()
        return len(abandoned)
