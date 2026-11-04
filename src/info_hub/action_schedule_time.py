"""Fixed-interval UTC cadence math, without database or network dependencies."""
from datetime import datetime, timedelta

MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 10_080


def next_cadence_time(
    due: datetime, *, interval_minutes: int, now: datetime,
) -> datetime:
    """Advance to the first scheduled time strictly after now; no backlog replay."""
    if (
        type(interval_minutes) is not int
        or not MIN_INTERVAL_MINUTES <= interval_minutes <= MAX_INTERVAL_MINUTES
    ):
        raise ValueError("Invalid Action schedule interval")
    if due.tzinfo is None or now.tzinfo is None:
        raise ValueError("Action scheduling requires timezone-aware timestamps")
    if due > now:
        return due
    period = timedelta(minutes=interval_minutes)
    missed = (now - due) // period
    return due + period * (missed + 1)
