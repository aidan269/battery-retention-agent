"""Validated operational inputs; battery charge is not proof of an outage."""
from dataclasses import asdict, dataclass
from datetime import datetime
import math
from typing import Literal


@dataclass(frozen=True)
class BatteryEvent:
    event_id: str
    dispatch_id: str | None
    customer_id: str
    observed_at: datetime
    phase: Literal["started", "updated", "ended"]
    battery_percent: float
    reserve_percent: float
    dispatch_confirmed: bool
    grid_status: Literal["available", "outage", "unknown"]
    verified_reason: str | None
    customer_requested_human: bool = False

    def __post_init__(self):
        for name in ("event_id", "customer_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if self.dispatch_id is not None and (
            not isinstance(self.dispatch_id, str) or not self.dispatch_id.strip()
        ):
            raise ValueError("dispatch_id must be a nonempty string or null")
        for name in ("dispatch_confirmed", "customer_requested_human"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.dispatch_confirmed and not self.dispatch_id:
            raise ValueError("Confirmed dispatch needs a dispatch_id")
        for name in ("battery_percent", "reserve_percent"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be a finite number between 0 and 100")
        if not isinstance(self.observed_at, datetime) or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        if self.phase not in ("started", "updated", "ended"):
            raise ValueError("Invalid event phase")
        if self.grid_status not in ("available", "outage", "unknown"):
            raise ValueError("Invalid grid status")
        if self.verified_reason is not None and not isinstance(self.verified_reason, str):
            raise ValueError("verified_reason must be text or null")

    def to_dict(self):
        return {**asdict(self), "observed_at": self.observed_at.isoformat()}

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["observed_at"] = datetime.fromisoformat(data["observed_at"])
        return cls(**data)
