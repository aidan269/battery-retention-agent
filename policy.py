"""Prototype thresholds, not verified Base Power operating policy."""
from dataclasses import dataclass
from datetime import datetime, timezone
from models import BatteryEvent


@dataclass(frozen=True)
class Decision:
    notify: bool
    escalate: bool
    reasons: tuple[str, ...]


NOTIFICATION_THRESHOLDS = (30, 25)
BATTERY_FLOOR = 20


def crossed_thresholds(previous_percent, current_percent):
    if previous_percent is None:
        return ()
    return tuple(t for t in NOTIFICATION_THRESHOLDS
                 if previous_percent > t >= current_percent)


def decide(event: BatteryEvent, *, previous_percent=None, now=None, max_age_seconds=900) -> Decision:
    now = now or datetime.now(timezone.utc)
    reasons = []
    age = (now - event.observed_at).total_seconds()
    stale = age > max_age_seconds or age < -60
    if stale:
        reasons.append("stale_or_future_telemetry")
    if event.customer_requested_human:
        reasons.append("customer_requested_human")
    if event.grid_status == "outage":
        reasons.append("grid_outage")
    if event.battery_percent < BATTERY_FLOOR:
        reasons.append("below_battery_floor")
    if event.battery_percent < event.reserve_percent:
        reasons.append("below_configured_reserve")
    if event.grid_status == "unknown":
        reasons.append("unknown_grid_status")
    if not event.dispatch_confirmed:
        reasons.append("unconfirmed_dispatch")
    if not event.verified_reason or not event.verified_reason.strip():
        reasons.append("missing_dispatch_reason")

    notify = (
        not stale and event.dispatch_confirmed and event.phase != "ended"
        and event.battery_percent >= BATTERY_FLOOR
        and bool(crossed_thresholds(previous_percent, event.battery_percent))
    )
    return Decision(notify, bool(reasons), tuple(reasons))



def queue_for(reason: str) -> str:
    if reason in {"grid_outage", "below_configured_reserve", "reported_outage", "below_battery_floor"}:
        return "operations"
    if reason in {"customer_requested_human", "cancellation_intent"}:
        return "customer_support"
    return "review"
