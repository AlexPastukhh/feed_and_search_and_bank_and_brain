"""Record completed external AI work without enqueueing the Action Worker.

This is a write-audited fact reported by an authenticated executor, not a command
to launch an AI and not an independent confirmation of external data storage.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_models import Action
from info_hub.action_run_models import ActionResult, ActionRun
from info_hub.action_run_services import RunConflict, RunNotFound
from info_hub.action_services import get_action_version


def register_external_run(
    session: Session, *, action_id: int, version_number: int,
    external_run_key: str, executor_id: str, initiated_by: str,
    status: str, summary: str, started_at: datetime | None,
    finished_at: datetime | None, output_refs: list[str],
    storage_status: str, registration_fingerprint: str,
    error_code: str | None = None,
) -> tuple[ActionRun, bool]:
    """One transaction and one idempotency key per Action; no queued/run steps.

    Locking the Action row serializes registrations for a stable key. Concurrent
    calls with the same payload return the same result, and changed submissions
    are rejected rather than rewriting historical evidence.
    """
    action = session.scalar(
        select(Action).where(Action.id == action_id).with_for_update()
    )
    if action is None:
        raise RunNotFound("Action not found")
    version = get_action_version(
        session, action_id=action_id, version_number=version_number,
    )
    if version is None:
        raise RunNotFound("Action version not found")
    existing = session.scalar(
        select(ActionRun).where(
            ActionRun.action_id == action_id,
            ActionRun.external_run_key == external_run_key,
        )
    )
    if existing is not None:
        if (existing.execution_kind != "external_ai"
                or existing.registration_fingerprint != registration_fingerprint
                or existing.executor_id != executor_id):
            raise RunConflict("External run key already registered with different data")
        return existing, False

    record = ActionRun(
        action_id=action_id, action_version_id=version.id,
        status=status, initiated_by=initiated_by, execution_kind="external_ai",
        executor_id=executor_id, external_run_key=external_run_key,
        registration_fingerprint=registration_fingerprint,
        started_at=started_at, finished_at=finished_at,
        error_code=error_code,
    )
    session.add(record)
    session.flush()
    session.add(ActionResult(
        action_run_id=record.id, status=status, summary=summary,
        details={
            "output_refs": output_refs,
            "storage_status": storage_status,
            # The Core does not dereference these URLs or attest to storage.
            "storage_evidence": "executor_reported",
        },
    ))
    session.commit()
    session.refresh(record)
    return record, True
