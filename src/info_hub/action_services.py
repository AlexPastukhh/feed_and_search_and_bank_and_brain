"""Action definition/version business logic; no tool calls or Feedbrain dependencies."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_models import Action, ActionVersion, utc_now
from info_hub.action_workflow import parse_action_yaml


class ActionNotFound(LookupError):
    pass


class ActionVersionConflict(ValueError):
    pass


def create_action(session: Session, *, source_yaml: str) -> tuple[Action, ActionVersion]:
    definition = parse_action_yaml(source_yaml)
    action = Action(name=definition["name"], current_version_number=1)
    session.add(action)
    session.flush()
    version = ActionVersion(
        action_id=action.id,
        version_number=1,
        source_yaml=source_yaml,
        definition=definition,
    )
    session.add(version)
    session.commit()
    return action, version


def publish_action_version(
    session: Session, *, action_id: int, expected_version: int, source_yaml: str,
) -> tuple[Action, ActionVersion]:
    """Lock Action for concurrent version publication; retain previous versions forever."""
    definition = parse_action_yaml(source_yaml)
    action = session.scalar(
        select(Action).where(Action.id == action_id).with_for_update()
    )
    if action is None:
        raise ActionNotFound("Action not found")
    if action.current_version_number != expected_version:
        raise ActionVersionConflict(
            f"Expected Action version {expected_version}, "
            f"but current version is {action.current_version_number}"
        )
    new_number = action.current_version_number + 1
    version = ActionVersion(
        action_id=action.id, version_number=new_number,
        source_yaml=source_yaml, definition=definition,
    )
    session.add(version)
    action.name = definition["name"]
    action.current_version_number = new_number
    action.updated_at = utc_now()
    session.commit()
    return action, version


def get_action_version(
    session: Session, *, action_id: int, version_number: int,
) -> ActionVersion | None:
    return session.scalar(
        select(ActionVersion).where(
            ActionVersion.action_id == action_id,
            ActionVersion.version_number == version_number,
        )
    )
