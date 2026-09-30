"""Offline demonstration; pass --live-claude to request an actual draft."""
import argparse
import json
from datetime import datetime, timezone
from uuid import uuid4
from models import BatteryEvent
from workflow import RetentionWorkflow
from writer import draft_message, fallback_message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="retention.sqlite3")
    parser.add_argument("--live-claude", action="store_true")
    args = parser.parse_args()
    if args.live_claude:
        from dotenv import load_dotenv
        load_dotenv()
    run_id = uuid4().hex[:10]
    event = BatteryEvent(
        event_id=f"reading-{run_id}", dispatch_id=f"dispatch-{run_id}",
        customer_id="demo-customer", observed_at=datetime.now(timezone.utc),
        phase="updated", battery_percent=19, reserve_percent=20,
        dispatch_confirmed=True, grid_status="available",
        verified_reason="Battery export during elevated grid demand (simulated event).",
    )
    with RetentionWorkflow(args.db, writer=draft_message if args.live_claude else fallback_message,
                           writer_source="claude" if args.live_claude else "offline_template") as workflow:
        for label in ("First event", "Repeated event"):
            print(label)
            print(json.dumps(workflow.handle(event), indent=2))
        print("Local escalation queue")
        print(json.dumps(workflow.list_records("escalations"), indent=2))


if __name__ == "__main__":
    main()
