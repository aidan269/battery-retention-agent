One recurring concern I saw in Facebook discussions about Base Power was a lack of transparency around battery drainage during peak grid demand. I built this customer retention bot to help explain these events, flag customer concerns, and keep an engineer in the loop.

```text
Battery dispatch event
         |
         v
Check battery level and grid status
         |
         +---- Concern detected ----> Engineer review
         |
         v
Claude drafts a customer update
         |
         v
Human review before sending
```

The prototype also includes Jev for assessing customer replies. Next, I want to expand its role in identifying cancellation intent, routing concerns to the right team, and flagging ambiguous replies for human review.

Thank you, team!
