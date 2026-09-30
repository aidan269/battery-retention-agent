"""Persistent local harness. No external customer messages or tickets are sent."""
import json
import sqlite3
from datetime import datetime, timezone

from jev import assess_customer_reply, reply_reasons
from models import BatteryEvent
from policy import decide, milestone, queue_for
from writer import draft_message, fallback_message

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
    dispatch_id TEXT, observed_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY, customer_id TEXT NOT NULL, incident_id TEXT NOT NULL,
    reason TEXT NOT NULL, queue TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
    event_id TEXT, UNIQUE(customer_id, incident_id, reason)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, customer_id TEXT NOT NULL, dispatch_id TEXT NOT NULL,
    milestone TEXT NOT NULL, event_id TEXT NOT NULL, message TEXT NOT NULL,
    source TEXT NOT NULL, error_type TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    UNIQUE(customer_id, dispatch_id, milestone)
);
CREATE TABLE IF NOT EXISTS replies (
    reply_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, dispatch_id TEXT NOT NULL,
    text TEXT NOT NULL, requested_human INTEGER NOT NULL,
    assessment TEXT NOT NULL, error_type TEXT
);
"""


class RetentionWorkflow:
    def __init__(self, db_path="retention.sqlite3", *, writer=draft_message,
                 assessor=assess_customer_reply, writer_source="claude"):
        self.db = sqlite3.connect(db_path, timeout=120)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.writer = writer
        self.assessor = assessor
        self.writer_source = writer_source

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _escalate(self, customer, incident, reason, event_id=None):
        self.db.execute(
            "INSERT INTO escalations(customer_id, incident_id, reason, queue, event_id) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(customer_id, incident_id, reason) "
            "DO UPDATE SET event_id=COALESCE(excluded.event_id, escalations.event_id)",
            (customer, incident, reason, queue_for(reason), event_id),
        )

    def handle(self, event: BatteryEvent, *, now=None):
        now = now or datetime.now(timezone.utc)
        decision = decide(event, now=now)
        payload = json.dumps(event.to_dict(), sort_keys=True)
        incident = event.dispatch_id or event.event_id
        # Commit the operational record and handoff before any model call.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT payload FROM events WHERE event_id=?", (event.event_id,)).fetchone()
            if old and old["payload"] != payload:
                raise ValueError("event_id already exists with different data")
            self.db.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?)",
                            (event.event_id, event.customer_id, event.dispatch_id,
                             event.observed_at.isoformat(), payload))
            for reason in decision.reasons:
                self._escalate(event.customer_id, incident, reason, event.event_id)

        result = {"event_id": event.event_id, "escalation_reasons": list(decision.reasons)}
        if not decision.notify:
            return {**result, "status": "no_notification"}

        # A local single-worker prototype: serialize generation so concurrent
        # callers cannot create duplicate drafts. Rollback makes crash retry safe.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            key = (event.customer_id, event.dispatch_id, milestone(event))
            existing = self.db.execute(
                "SELECT * FROM notifications WHERE customer_id=? AND dispatch_id=? AND milestone=?", key
            ).fetchone()
            if existing:
                return {**result, "status": "already_queued", "notification": dict(existing)}
            # Do not send a delayed start/update after newer telemetry or an end.
            history = self.db.execute(
                "SELECT payload FROM events WHERE customer_id=? AND dispatch_id=? AND event_id<>?",
                (event.customer_id, event.dispatch_id, event.event_id),
            ).fetchall()
            for row in history:
                previous = BatteryEvent.from_dict(json.loads(row["payload"]))
                if (previous.observed_at - now).total_seconds() > 60:
                    continue
                if (previous.observed_at > event.observed_at or
                    previous.phase == "ended" and event.phase != "ended"):
                    return {**result, "status": "superseded"}
            error_type = None
            source = self.writer_source
            try:
                # A local queue entry is not evidence that external support was contacted.
                message = self.writer(event, ticket_created=False)
                if not isinstance(message, str) or not message.strip() or len(message.split()) > 80:
                    raise ValueError("Invalid draft")
            except Exception as error:
                error_type = type(error).__name__
                message = fallback_message(event)
                source = "fallback"
                self._escalate(event.customer_id, incident, "generation_failed", event.event_id)
                result["escalation_reasons"].append("generation_failed")
            cursor = self.db.execute(
                "INSERT INTO notifications(customer_id, dispatch_id, milestone, event_id, message, source, error_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*key, event.event_id, message, source, error_type),
            )
            notification = dict(self.db.execute("SELECT * FROM notifications WHERE id=?", (cursor.lastrowid,)).fetchone())
        return {**result, "status": "queued_for_review", "notification": notification}

    def handle_reply(self, reply_id, customer_id, dispatch_id, text, *, requested_human=False):
        if any(not isinstance(v, str) or not v.strip() for v in (reply_id, customer_id, dispatch_id, text)):
            raise ValueError("Reply identifiers and text are required")
        if type(requested_human) is not bool:
            raise ValueError("requested_human must be boolean")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT * FROM replies WHERE reply_id=?", (reply_id,)).fetchone()
            if existing:
                if (existing["customer_id"], existing["dispatch_id"], existing["text"], bool(existing["requested_human"])) != (
                    customer_id, dispatch_id, text, requested_human
                ):
                    raise ValueError("reply_id already exists with different data")
                return dict(existing)
            records = self.db.execute("SELECT payload FROM events WHERE customer_id=? AND dispatch_id=?",
                                      (customer_id, dispatch_id)).fetchall()
            if not records:
                raise ValueError("Unknown customer/dispatch pair")
            latest = max((BatteryEvent.from_dict(json.loads(r["payload"])) for r in records),
                         key=lambda e: e.observed_at)
            if requested_human:
                self._escalate(customer_id, dispatch_id, "customer_requested_human", latest.event_id)

        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            # Recheck after releasing the lock for the explicit human handoff.
            existing = self.db.execute("SELECT * FROM replies WHERE reply_id=?", (reply_id,)).fetchone()
            if existing:
                if (existing["customer_id"], existing["dispatch_id"], existing["text"], bool(existing["requested_human"])) != (
                    customer_id, dispatch_id, text, requested_human
                ):
                    raise ValueError("reply_id already exists with different data")
                return dict(existing)
            error_type = None
            scores = {}
            context = {k: v for k, v in latest.to_dict().items()
                       if k not in {"customer_id", "event_id", "dispatch_id"}}
            try:
                scores = self.assessor(text, context)
                reasons = reply_reasons(scores)
            except Exception as error:
                scores = {}
                error_type = type(error).__name__
                reasons = ["reply_assessment_failed"]
            for reason in reasons:
                self._escalate(customer_id, dispatch_id, reason, latest.event_id)
            self.db.execute("INSERT INTO replies VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (reply_id, customer_id, dispatch_id, text, requested_human,
                             json.dumps(scores), error_type))
            return dict(self.db.execute("SELECT * FROM replies WHERE reply_id=?", (reply_id,)).fetchone())

    def list_records(self, table):
        if table not in {"events", "notifications", "escalations", "replies"}:
            raise ValueError("Unknown table")
        return [dict(row) for row in self.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def review(self, notification_id, *, approve):
        with self.db:
            status = "approved" if approve else "rejected"
            cursor = self.db.execute(
                "UPDATE notifications SET status=? WHERE id=? AND status='pending_review'",
                (status, notification_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Notification must exist and be pending review")
        return {"id": notification_id, "status": status}
