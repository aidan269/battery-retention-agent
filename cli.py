"""Local operator CLI. Approval does not send a message."""
import argparse
import json
from pathlib import Path
from crm import write_escalation
from models import BatteryEvent
from workflow import RetentionWorkflow
from writer import draft_message, fallback_message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="retention.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("file")
    ingest.add_argument("--live-claude", action="store_true")
    listing = commands.add_parser("list")
    listing.add_argument("table", choices=["events", "notifications", "escalations", "replies"])
    for name in ("approve", "reject"):
        sub = commands.add_parser(name)
        sub.add_argument("id", type=int)
    reply = commands.add_parser("reply", help="Assess a reply with Jev, or queue for review without --live-jev")
    reply.add_argument("reply_id")
    reply.add_argument("customer_id")
    reply.add_argument("dispatch_id")
    reply.add_argument("text")
    reply.add_argument("--requested-human", action="store_true")
    reply.add_argument("--live-jev", action="store_true")
    reply.add_argument("--hubspot-contact-id", help="Create a HubSpot task if this reply is escalated")
    args = parser.parse_args()
    if (getattr(args, "live_claude", False) or getattr(args, "live_jev", False)
            or getattr(args, "hubspot_contact_id", None)):
        from dotenv import load_dotenv
        load_dotenv()
    options = {}
    if not getattr(args, "live_claude", False):
        options.update(writer=fallback_message, writer_source="offline_template")
    if args.command == "reply" and not args.live_jev:
        def offline_assessor(*unused):
            raise RuntimeError("Live Jev assessment disabled")
        options["assessor"] = offline_assessor
    try:
        with RetentionWorkflow(args.db, **options) as workflow:
            if args.command == "ingest":
                output = workflow.handle(BatteryEvent.from_dict(json.loads(Path(args.file).read_text())))
            elif args.command == "list":
                output = workflow.list_records(args.table)
            elif args.command in {"approve", "reject"}:
                output = workflow.review(args.id, approve=args.command == "approve")
            else:
                output = workflow.handle_reply(args.reply_id, args.customer_id, args.dispatch_id,
                                               args.text, requested_human=args.requested_human)
                if args.hubspot_contact_id:
                    output["hubspot"] = write_escalation(workflow.db, output, args.hubspot_contact_id)
        print(json.dumps(output, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
