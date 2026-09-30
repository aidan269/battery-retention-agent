import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from jev import assess_customer_reply
from models import BatteryEvent
from workflow import RetentionWorkflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.now = datetime.now(timezone.utc)
        self.event = BatteryEvent('e1', 'd1', 'c1', self.now, 'started', 70, 20,
                                  True, 'available', 'Confirmed grid demand event')
        self.writer = Mock(return_value='Your confirmed battery dispatch has started.')
        self.assessor = Mock(return_value={'human_requested': 0.01, 'cancellation': 0.01, 'outage': 0.01})
        self.w = RetentionWorkflow(self.path, writer=self.writer, assessor=self.assessor)

    def tearDown(self):
        self.w.close()
        self.temp.cleanup()

    def test_persistent_deduplication(self):
        first = self.w.handle(self.event)
        with RetentionWorkflow(self.path, writer=self.writer) as second:
            result = second.handle(self.event)
        self.assertEqual(result['status'], 'already_queued')
        self.assertEqual(first['notification']['id'], result['notification']['id'])
        self.writer.assert_called_once()

    def test_new_readings_same_milestone(self):
        self.w.handle(replace(self.event, phase='updated', battery_percent=24))
        result = self.w.handle(replace(self.event, event_id='e2', phase='updated', battery_percent=23))
        self.assertEqual(result['status'], 'already_queued')
        self.writer.assert_called_once()

    def test_breach_gets_new_alert(self):
        self.w.handle(replace(self.event, phase='updated', battery_percent=24))
        result = self.w.handle(replace(self.event, event_id='e2', phase='updated', battery_percent=19))
        self.assertEqual(result['status'], 'queued_for_review')
        ticket = self.w.list_records('escalations')[0]
        self.assertEqual(ticket['reason'], 'below_configured_reserve')
        self.assertEqual(ticket['queue'], 'operations')

    def test_outage_above_reserve(self):
        result = self.w.handle(replace(self.event, phase='updated', grid_status='outage'))
        self.assertEqual(result['notification']['milestone'], 'outage')
        self.assertIn('grid_outage', result['escalation_reasons'])

    def test_end_notification_after_reserve_breach(self):
        self.w.handle(replace(self.event, phase='updated', battery_percent=19))
        result = self.w.handle(replace(self.event, event_id='end', phase='ended', battery_percent=19))
        self.assertEqual(result['notification']['milestone'], 'ended')
        self.assertEqual(result['status'], 'queued_for_review')

    def test_escalation_committed_before_claude_failure(self):
        def fail(event, **kwargs):
            with RetentionWorkflow(self.path) as reader:
                self.assertTrue(reader.list_records('escalations'))
            raise TimeoutError('secret must not be stored')
        self.w.writer = fail
        result = self.w.handle(replace(self.event, battery_percent=19))
        self.assertEqual(result['notification']['source'], 'fallback')
        self.assertEqual(result['notification']['error_type'], 'TimeoutError')
        self.assertNotIn('secret', json.dumps(self.w.list_records('notifications')))

    def test_stale_and_future_readings(self):
        for minutes in (-16, 2):
            result = self.w.handle(replace(self.event, event_id=str(minutes),
                                           observed_at=self.now + timedelta(minutes=minutes)), now=self.now)
            self.assertEqual(result['status'], 'no_notification')
            self.assertIn('stale_or_future_telemetry', result['escalation_reasons'])
        self.writer.assert_not_called()

    def test_unknown_cause_is_reviewed(self):
        result = self.w.handle(replace(self.event, dispatch_confirmed=False,
                                       dispatch_id=None, verified_reason=None))
        self.assertEqual(result['status'], 'no_notification')
        self.assertIn('unconfirmed_dispatch', result['escalation_reasons'])

    def test_input_validation(self):
        for value in (-1, 101, float('nan'), float('inf'), True, '20'):
            with self.assertRaises(ValueError):
                replace(self.event, battery_percent=value)
        with self.assertRaises(ValueError):
            replace(self.event, observed_at=datetime.now())
        with self.assertRaises(ValueError):
            replace(self.event, dispatch_id=None)

    def test_event_id_collision_rejected(self):
        self.w.handle(self.event)
        with self.assertRaises(ValueError):
            self.w.handle(replace(self.event, battery_percent=10))

    def test_late_start_suppressed(self):
        self.w.handle(replace(self.event, phase='ended'))
        result = self.w.handle(replace(self.event, event_id='late',
                                       observed_at=self.now - timedelta(seconds=30)))
        self.assertEqual(result['status'], 'superseded')

    def test_review_state_transitions(self):
        identifier = self.w.handle(self.event)['notification']['id']
        self.assertEqual(self.w.review(identifier, approve=True)['status'], 'approved')
        with self.assertRaises(ValueError):
            self.w.review(identifier, approve=False)
        self.assertNotEqual(self.w.list_records('notifications')[0]['status'], 'sent')

    def test_reply_escalations_and_dedup(self):
        self.w.handle(self.event)
        self.assessor.return_value = {'human_requested': 0.9, 'cancellation': 0.95, 'outage': 0.5}
        first = self.w.handle_reply('r1', 'c1', 'd1', 'I want to cancel')
        second = self.w.handle_reply('r1', 'c1', 'd1', 'I want to cancel')
        self.assertEqual(first, second)
        self.assessor.assert_called_once()
        reasons = {r['reason'] for r in self.w.list_records('escalations')}
        self.assertEqual(reasons, {'customer_requested_human', 'cancellation_intent', 'uncertain_reply'})

    def test_human_request_survives_jev_failure(self):
        self.w.handle(self.event)
        self.assessor.side_effect = TimeoutError()
        self.w.handle_reply('r1', 'c1', 'd1', 'help', requested_human=True)
        reasons = {r['reason'] for r in self.w.list_records('escalations')}
        self.assertIn('customer_requested_human', reasons)
        self.assertIn('reply_assessment_failed', reasons)

    def test_malformed_jev_result_routes_to_review(self):
        self.w.handle(self.event)
        self.assessor.return_value = {'outage': float('nan')}
        self.w.handle_reply('r1', 'c1', 'd1', 'help')
        self.assertEqual(self.w.list_records('escalations')[0]['reason'], 'reply_assessment_failed')

    def test_reply_must_match_customer_dispatch(self):
        self.w.handle(self.event)
        with self.assertRaises(ValueError):
            self.w.handle_reply('r1', 'other', 'd1', 'help')
        self.assessor.assert_not_called()

    def test_concurrent_event_dedup(self):
        def handle(_):
            with RetentionWorkflow(self.path, writer=lambda *a, **kw: 'Draft') as worker:
                return worker.handle(self.event)['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(handle, range(2)))
        self.assertCountEqual(statuses, ['queued_for_review', 'already_queued'])
        self.assertEqual(len(self.w.list_records('notifications')), 1)

    @patch.dict('os.environ', {'TYPESAFE_API_KEY': 'test-key'})
    @patch('jev.urlopen')
    def test_jev_http_contract(self, urlopen):
        scores = {'human_requested': 0.9, 'cancellation': 0.1, 'outage': 0.05}
        body = {'answers': {k: {'type': 'noul', 'noul': v} for k, v in scores.items()}}
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(body).encode()
        self.assertEqual(assess_customer_reply('help', {}), scores)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.typesafe.ai/v1/systemone')
        payload = json.loads(request.data)
        self.assertEqual(set(payload['questions']), set(scores))
        self.assertEqual(payload['state']['customer_reply'], 'help')


if __name__ == '__main__':
    unittest.main()
