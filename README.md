# Base customer retention bot — v1.0 local prototype

Confirmed dispatch events produce customer message drafts and local human handoffs.
Python owns the workflow and operational rules; Claude writes; Jev assesses replies.
All messages require review. There is no SMS/email delivery or external ticket integration.
This prototype does not control batteries or infer grid demand from battery charge.

## Quick start (no credentials or dependencies needed)

Requires Python 3.10+.

```bash
python3 demo.py
python3 cli.py list notifications
python3 cli.py list escalations
python3 cli.py approve 1
python3 -m unittest discover -s tests -v
```

The demo creates a simulated below-reserve event, processes it twice, and shows the
persistent draft and escalation. Each demo run uses a new dispatch ID. The second
handling within a run demonstrates deduplication. Data is stored in `retention.sqlite3`.
Use `--db /path/to/test.sqlite3` to choose another database (before the subcommand
for cli.py). Approval only changes local review status; it never sends anything.
`python3 cli.py reject 1` rejects a pending draft instead.

## Live Claude and Jev

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Fill in `.env` using `.env.example` as a guide. Preserve any existing values.
Set `CLAUDE_MODEL` to an available model ID from your Anthropic account.
`JEV_MODEL` defaults to `jev-latest`. Environment variables take precedence over
`.env`. Credentials and local databases are ignored by Git.

```bash
python demo.py --live-claude
```

This makes a billable Claude call using simulated event data. A missing key,
model error, timeout, or invalid draft creates a fallback and a review escalation;
inspect `source` and `error_type` to distinguish a successful live call from fallback.
Error types, not exception messages or API keys, are stored.

For a real event, create a JSON file matching the schema below and update its
observation time. Then run:

```bash
python cli.py ingest event.json --live-claude
```

Without `--live-claude`, ingestion uses a deterministic template. Example shape
(the timestamp is illustrative; stale events are held for review):

```json
{
  "event_id": "reading-001",
  "dispatch_id": "dispatch-001",
  "customer_id": "customer-001",
  "observed_at": "2026-09-29T22:00:00+00:00",
  "phase": "updated",
  "battery_percent": 22,
  "reserve_percent": 20,
  "dispatch_confirmed": true,
  "grid_status": "available",
  "verified_reason": "Confirmed battery export during elevated grid demand.",
  "customer_requested_human": false
}
```

Only populate dispatch confirmation, reason, grid status, and reserve from trusted
operational sources. The customer/dispatch pair must exist before ingesting replies.
Use the IDs printed by the demo or your event:

```bash
python cli.py reply reply-001 customer-001 dispatch-001 "I want to cancel" --live-jev
python cli.py reply reply-002 customer-001 dispatch-001 "Please contact me" --requested-human
python cli.py list replies
python cli.py list escalations
```

The first command sends the reply and operational context to Jev. The second
immediately creates a local support handoff and, without `--live-jev`, queues the
unclassified reply for review. Explicit human requests survive a Jev failure.
Raw free text can contain customer-provided personal information; use synthetic
replies for the demo. Customer identifiers are excluded from model context.

## Code map

- `models.py`: event validation and JSON conversion, including timezone and finite percentages.
- `policy.py`: alert milestones, freshness, hard escalation rules and queue mapping.
- `writer.py`: Claude adapter and deterministic fallback; drafts cannot claim an external ticket exists.
- `workflow.py`: SQLite harness, deduplication, local handoffs, review states, and reply handling.
- `jev.py`: documented TypeSafe HTTP adapter, validated probabilities, and reply routing.
- `cli.py`: event ingestion, review, inspection, and Jev reply assessment.
- `demo.py`: synthetic end-to-end example, offline by default.
- `tests/test_workflow.py`: regression tests with fake model responses; no network needed.

## Behavior and boundaries

Notifications are unique per customer + dispatch + milestone. Milestones include
start, near reserve, below reserve, outage, and end. Ending a dispatch does not imply
the battery has recharged or grid power has returned. Replayed events are safe;
reusing an event/reply ID for different data is rejected. Delayed older notifications
are suppressed. A dispatch ID must represent one incident and cannot be reused.

Prototype thresholds: near reserve is reserve + 5 percentage points; telemetry
older than 15 minutes or over 60 seconds in the future requires review. These values,
including the demo's 20% reserve, are not verified Base policy. Escalation records
are committed before Claude generation. Missing/unconfirmed causes, unknown grid
status, stale telemetry, and provider failures remain visible in the review queue.

Jev answers three separate Noul questions: human request, cancellation intent,
and reported outage. Probabilities >= 0.8 create the matching escalation; values
strictly between 0.2 and 0.8 require review. Lower scores create no model-derived
handoff. These thresholds are illustrative and need evaluation on labeled replies.
An explicit human-request flag and operational rules cannot be overridden by Jev.
Invalid/missing assessments and network failures route to review. No automatic
Jev retry loop is used in v1; a reviewer can follow up on the saved failure.

Escalations are durable **local queue items**, not external support tickets.
`operations`, `customer_support`, and `review` are proposed queue names. Drafts have
`pending_review`, `approved`, or `rejected` status; there is deliberately no fake
`sent` status. Reviewers should verify facts and timestamp freshness before any
manual use of a draft. Rejected drafts remain deduplicated for that milestone.

SQLite serializes generation under a write transaction for this small local demo.
This protects draft uniqueness, but long model calls block other writers. A crash
rolls back the draft transaction; replaying the event can regenerate it while
preserving already committed operational handoffs. This is not a high-throughput
worker system. Pending drafts are snapshots and are not automatically rewritten
when newer telemetry arrives; review against the event history.

## What is needed for live customer operation

Connect an authenticated dispatch/telemetry feed, confirm Base's rules and queue
ownership, and add an actual ticket and notification provider. Delivery needs a
transactional outbox, provider idempotency keys, retries and recorded receipts;
approved must remain distinct from sent. Add operator authentication and retention
controls before exposing this CLI/storage as a service. Model output still needs
factual review; schema-valid Jev answers are not guaranteed correct.

## API references

- Anthropic Python SDK: https://github.com/anthropics/anthropic-sdk-python
- Jev HTTP request/response contract: https://docs.typesafe.ai/api
- TypeSafe probability/confidence distinction: https://docs.typesafe.ai/confidence

Live providers are opt-in and were not used for the local automated tests.
