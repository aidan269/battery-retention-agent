# Battery Retention Bot v1 🔋

One recurring concern I saw in discussions about [Base Power](https://www.basepowercompany.com/) was a lack of transparency around battery drainage during peak grid demand. I built this customer retention bot to help explain these events, flag customer concerns, and keep an engineer in the loop.

The bot prepares one customer update when charge crosses 30% and another at 25%, per dispatch.

```text
Battery reading arrives
          |
          v
Confirmed dispatch + fresh telemetry?
          |
          v
Crossed 30% or 25% since the previous reading?
          |
          v
Claude drafts a customer update
          |
          v
Human review before sending
```

```text
35% -> 31% -> 30% -> 28% -> 25% -> 22% -> 20%
              |             |
            draft         draft
```

Run `python3 demo.py` to see the sequence offline, or `python3 demo.py --live-claude` with Claude credentials configured. The first reading establishes a baseline. Skipped readings still count as crossings: 31% to 29% triggers the 30% update using the actual 29% reading. A jump across both thresholds produces one update at the lower threshold and marks both as handled.

Drafts stay in a local review queue. Jev assesses customer replies, and the bot can write escalations to HubSpot as follow-up tasks linked to the customer contact.

To write an escalation to HubSpot, set `HUBSPOT_ACCESS_TOKEN` in `.env` to a HubSpot app access token authorized to create tasks. Supply an existing test contact's numeric record ID (not the local customer ID):

```bash
python cli.py --db live-demo.sqlite3 reply reply-hubspot-001 demo-customer YOUR_DISPATCH_ID "I want to cancel and speak with someone" --live-jev --hubspot-contact-id YOUR_CONTACT_ID
```

Use the dispatch ID from your demo. When Jev flags the reply, this creates one **Battery customer escalation** task associated with that contact, containing the reply, reasons, and assessment. The output shows `hubspot.status: created` and the task ID. Without the flag there is no CRM write. Explicit human requests also qualify. Repeating the same reply ID in the same database does not create another task. `check_required` or `attempted` means inspect HubSpot before trying again; this demo deliberately does not retry ambiguous writes. Jev assesses replies; Claude writes customer messages.

API reference: [HubSpot task creation](https://developers.hubspot.com/docs/api-reference/legacy/crm/activities/tasks/create-task).
