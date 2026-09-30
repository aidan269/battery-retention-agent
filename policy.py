"""Prototype thresholds, not verified Base Power operating policy."""
from dataclasses import dataclass
from datetime import datetime, timezone
from models import BatteryEvent


@dataclass(frozen=True)
class Decision:
    notify: bool
    escalate: bool
    reasons: tuple[str, ...]


def decide(event: BatteryEvent, *, now=None, max_age_seconds=900) -> Decision:
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
    if event.battery_percent < event.reserve_percent:
        reasons.append("below_configured_reserve")
    if event.grid_status == "unknown":
        reasons.append("unknown_grid_status")
    if not event.dispatch_confirmed:
        reasons.append("unconfirmed_dispatch")
    if not event.verified_reason or not event.verified_reason.strip():
        reasons.append("missing_dispatch_reason")

    near_reserve = event.battery_percent <= event.reserve_percent + 5
    notify = not stale and event.dispatch_confirmed and (
        event.phase in {"started", "ended"} or near_reserve
        or event.grid_status == "outage"
    )
    return Decision(notify, bool(reasons), tuple(reasons))


def milestone(event: BatteryEvent) -> str:
    if event.phase == "ended":
        return "ended"
    # Operational exceptions get their own update even after a routine warning.
    if event.grid_status == "outage":
        return "outage"
    if event.battery_percent < event.reserve_percent:
        return "below_reserve"
    if event.phase in {"started", "ended"}:
        return event.phase
    return "near_reserve"


def queue_for(reason: str) -> str:
    if reason in {"grid_outage", "below_configured_reserve", "reported_outage"}:
        return "operations"
    if reason in {"customer_requested_human", "cancellation_intent"}:
        return "customer_support"
    return "review"
