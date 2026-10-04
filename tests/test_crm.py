import json
import sqlite3
import unittest
from unittest.mock import patch
from crm import write_escalation


class CRMTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.reply = dict(reply_id='r1', customer_id='c1', dispatch_id='d1',
                          text='Please cancel <script>', requested_human=False, error_type=None,
                          assessment=json.dumps(dict(human_requested=0.1, cancellation=0.95, unresolved_problem=0.1)))

    @patch.dict('os.environ', {'HUBSPOT_ACCESS_TOKEN': 'test-token'})
    @patch('crm.urlopen')
    def test_task_payload_and_duplicate(self, post):
        post.return_value.__enter__.return_value.read.return_value = b'{"id":"123"}'
        result = write_escalation(self.db, self.reply, '42')
        self.assertEqual(result['status'], 'created')
        self.assertEqual(result['task_id'], '123')
        request = post.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload['associations'][0]['to']['id'], '42')
        self.assertIn('cancellation_intent', payload['properties']['hs_task_body'])
        self.assertNotIn('<script>', payload['properties']['hs_task_body'])
        write_escalation(self.db, self.reply, '42')
        post.assert_called_once()

    @patch('crm.urlopen')
    def test_no_escalation_no_write(self, post):
        self.reply['assessment'] = json.dumps(dict(human_requested=0.1, cancellation=0.1, unresolved_problem=0.1))
        self.assertEqual(write_escalation(self.db, self.reply, '42')['status'], 'not_escalated')
        post.assert_not_called()

    @patch.dict('os.environ', {'HUBSPOT_ACCESS_TOKEN': 'test-token'})
    @patch('crm.urlopen', side_effect=TimeoutError())
    def test_failure_visible_and_not_blindly_retried(self, post):
        result = write_escalation(self.db, self.reply, '42')
        self.assertEqual(result['status'], 'check_required')
        self.assertEqual(result['error_type'], 'TimeoutError')
        write_escalation(self.db, self.reply, '42')
        post.assert_called_once()
