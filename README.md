# Base customer retention bot -- v1.0 local prototype

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
