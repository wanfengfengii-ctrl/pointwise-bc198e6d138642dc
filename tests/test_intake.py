import json
from copy import deepcopy
from pathlib import Path

from demo import load_case, open_station, stage_revision
from tests.support import CenterTestCase
from timing.intake.envelope import canonical_envelope
from timing.intake.lookup import get_received_station
from timing.intake.receipts import accept_station


class IntakeTests(CenterTestCase):
    def make_issue(self):
        case = load_case('shift')
        with open_station(Path(self.root) / 'north.sqlite', 'north') as (ledger, publisher):
            return stage_revision(ledger, publisher, case, case['north'])

    def test_receipt_replay_and_conflict(self):
        issued = self.make_issue()
        original = accept_station(self.intake, issued)
        replay_text = json.dumps(json.loads(canonical_envelope(issued)), indent=2)
        replay = accept_station(self.intake, replay_text)
        self.assertFalse(original.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual((replay.receipt_id, replay.replay_count), (original.receipt_id, 1))
        changed = json.loads(canonical_envelope(issued))
        changed['body']['conditions'][1]['interval']['upper'] = [3, 2]
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            accept_station(self.intake, json.dumps(changed))
        received = get_received_station(self.intake, original.receipt_id)
        self.assertEqual(received.station.envelope, issued)
        self.assertEqual(received.replay_count, 1)
        self.assertEqual(self.intake.connection.execute('SELECT count(*) FROM intake_receipts').fetchone()[0], 1)

    def test_malformed_envelope(self):
        raw = canonical_envelope(self.make_issue())
        original = json.loads(raw)
        wrong_identity = deepcopy(original)
        wrong_identity['body']['revision_id'] += 1
        missing_condition = deepcopy(original)
        missing_condition['body']['conditions'].pop()
        invalid_bounds = deepcopy(original)
        invalid_bounds['body']['conditions'][1]['interval']['upper'] = [2, 2]
        invalid_status = deepcopy(original)
        invalid_status['body']['conditions'][1]['status'] = 'conflict'
        invalid_anchors = deepcopy(original)
        invalid_anchors['body']['anchors'] = ['U', 'U']
        duplicate_coverage = deepcopy(original)
        duplicate_coverage['body']['candidates'] = ['A', 'A']
        wrong_version = deepcopy(original)
        wrong_version['version'] = True
        invalid = (wrong_identity, missing_condition, invalid_bounds, invalid_status,
                   invalid_anchors, duplicate_coverage, wrong_version)
        texts = [json.dumps(item) for item in invalid] + [raw[:-1], '{"version":1,' + raw[1:]]
        for text in texts:
            with self.subTest(payload=text), self.assertRaises(ValueError):
                accept_station(self.intake, text)
        self.assertEqual(self.intake.connection.execute('SELECT count(*) FROM intake_receipts').fetchone()[0], 0)
