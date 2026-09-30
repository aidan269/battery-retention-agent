"""Direct HubSpot task creation for the demo; no background worker."""
import json
import os
from datetime import datetime, timezone
from html import escape
from urllib.request import Request, urlopen

from jev import reply_reasons


def write_escalation(db, reply, contact_id):
    """Create one task for an escalated reply. Never automatically repeat a POST."""
    if not str(contact_id).isdigit():
        raise ValueError("Use the numeric HubSpot contact record ID")
    reasons = reply_reasons(json.loads(reply['assessment'])) if not reply['error_type'] else []
    if reply['requested_human']:
        reasons.append('customer_requested_human')
    if not reasons:
        return {'status': 'not_escalated'}
    token = os.environ.get('HUBSPOT_ACCESS_TOKEN')
    if not token:
        raise ValueError('Set HUBSPOT_ACCESS_TOKEN in .env')
    db.execute('''CREATE TABLE IF NOT EXISTS hubspot_writes (
        reply_id TEXT PRIMARY KEY, contact_id TEXT NOT NULL,
        status TEXT NOT NULL, task_id TEXT, error_type TEXT
    )''')
    with db:
        existing = db.execute('SELECT * FROM hubspot_writes WHERE reply_id=?',
                              (reply['reply_id'],)).fetchone()
        if existing:
            if existing['contact_id'] != str(contact_id):
                raise ValueError('This reply already has a different HubSpot contact')
            return dict(existing)
        # Persist before POST. An interrupted/uncertain request needs manual review,
        # not a blind retry that could create another task.
        db.execute('INSERT INTO hubspot_writes VALUES (?, ?, ?, NULL, NULL)',
                   (reply['reply_id'], str(contact_id), 'attempted'))
    body = '\n'.join([
        f"Customer: {reply['customer_id']}",
        f"Dispatch: {reply['dispatch_id']}",
        f"Reply: {reply['reply_id']}",
        f"Reasons: {', '.join(sorted(set(reasons)))}",
        f"Customer message: {reply['text']}",
        f"Jev assessment: {reply['assessment']}",
    ])
    payload = {
        'properties': {
            'hs_timestamp': datetime.now(timezone.utc).isoformat(),
            'hs_task_subject': 'Battery customer escalation',
            'hs_task_body': escape(body).replace('\n', '<br>'),
            'hs_task_status': 'NOT_STARTED',
            'hs_task_type': 'TODO',
        },
        'associations': [{
            'to': {'id': str(contact_id)},
            'types': [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 204}],
        }],
    }
    request = Request('https://api.hubapi.com/crm/v3/objects/tasks',
                      data=json.dumps(payload).encode(), method='POST',
                      headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=20) as response:
            task_id = str(json.load(response)['id'])
    except Exception as error:
        with db:
            db.execute("UPDATE hubspot_writes SET status='check_required', error_type=? WHERE reply_id=?",
                       (type(error).__name__, reply['reply_id']))
    else:
        with db:
            db.execute("UPDATE hubspot_writes SET status='created', task_id=? WHERE reply_id=?",
                       (task_id, reply['reply_id']))
    return dict(db.execute('SELECT * FROM hubspot_writes WHERE reply_id=?', (reply['reply_id'],)).fetchone())
