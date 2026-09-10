"""Public daily schedule and execution contracts. Daily boundaries are Korea time."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, field_validator

from customer_signal.signals.contracts import Contract, Measurement

KOREA = ZoneInfo("Asia/Seoul")
DAY = timedelta(days=1)


def next_midnight(at: datetime) -> datetime:
    return (
        at.astimezone(KOREA).replace(hour=0, minute=0, second=0, microsecond=0) + DAY
    ).astimezone(timezone.utc)


class ScheduleUpdate(Contract):
    enabled: bool
    next_run_at: AwareDatetime | None = None

    @field_validator("next_run_at")
    @classmethod
    def midnight_only(cls, value):
        if value is not None:
            local = value.astimezone(KOREA)
            if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
                raise ValueError("next_run_at은 한국시간 자정이어야 합니다.")
            return value.astimezone(timezone.utc)
        return value


class DailySchedule(Contract):
    signal_id: str
    enabled: bool = True
    interval: Literal["daily"] = "daily"
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    next_run_at: AwareDatetime
    updated_at: AwareDatetime
    signal_status: Literal["active", "paused", "archived"]


class DailyResult(Contract):
    execution_id: str
    signal_id: str
    start_at: AwareDatetime
    end_at: AwareDatetime
    status: Literal["running", "success", "unavailable"]
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    measurement: Measurement | None = None


class DailyResults(Contract):
    items: list[DailyResult]
    next_before: AwareDatetime | None = None
    pending_days: int = Field(ge=0)
