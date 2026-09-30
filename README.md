# Battery Retention Bot v1 🔋

**Stack: Claude, Jev, Python, HubSpot**

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

Run `python3 demo.py` to see the sequence offline, or `python3 demo.py --live-claude` with Claude credentials configured. The first reading establishes a baseline. Skipped readings still count as crossings: 31% to 29% triggers the 30% update using the actual 29% reading. Drafts stay in a local review queue. Jev assesses customer replies, and the bot can write escalations to HubSpot as follow-up tasks linked to the customer contact. To write an escalation to HubSpot, set `HUBSPOT_ACCESS_TOKEN` in `.env` to a HubSpot app access token authorized to create tasks. 

When Jev flags the reply, this creates one **Battery customer escalation** task associated with that contact, containing the reply, reasons, and assessment. The output shows `hubspot.status: created` and the task ID.
