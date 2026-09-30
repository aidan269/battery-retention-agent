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

Drafts stay in a local review queue; customer delivery and CRM integration are not connected yet.

The prototype also includes Jev for assessing customer replies. Next, I want to expand its role in identifying cancellation intent, routing concerns to the right team, and flagging ambiguous replies for human review.

Thank you, team!
