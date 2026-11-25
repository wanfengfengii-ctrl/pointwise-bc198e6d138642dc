import unittest
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from demo import load_case, open_station, stage_revision
from timing.intake.checks import verify_station
from timing.intake.envelope import canonical_envelope
from timing.issue.intervals import TimeInterval
from timing.source.observations import Observation
from timing.source.revisions import load_revision, register_round, save_revision
from timing.source.rounds import RoundSpec
from timing.source.vouchers import Voucher


class IssueTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory(prefix='timing-issue-')))
        self.path = self.root / 'north.sqlite'
        self.case = load_case('shift')

    def test_issue_closed_interval(self):
        with open_station(self.path, 'north') as (ledger, publisher):
            issued = stage_revision(ledger, publisher, self.case, [['U', 'V', 2, 'A'], ['V', 'U', -1, 'C']])
            evidence = verify_station(issued).evidence
            self.assertEqual(evidence.conditions[0].interval, TimeInterval(1, 2))
            self.assertEqual(evidence.conditions[1].interval, TimeInterval(1, None))
            self.assertEqual(evidence.conditions[2].interval, TimeInterval(1, 2))
            self.assertEqual(evidence.anchors, ('U', 'V'))
            self.assertEqual(evidence.revision_id, load_revision(ledger, issued.revision_id).revision_id)
            self.assertEqual(evidence.issue_id, issued.issue_id)

    def test_fractional_path(self):
        rows = [['U', 'X', '1/10', 'A'], ['X', 'V', '1/5', 'B'], ['V', 'U', 0, 'C']]
        with open_station(self.path, 'north') as (ledger, publisher):
            issued = stage_revision(ledger, publisher, self.case, rows)
            fetched = publisher.get_issued_station(issued.issue_id)
            evidence = verify_station(fetched).evidence
            self.assertEqual(evidence.conditions[0].interval, TimeInterval(0, Fraction(3, 10)))
            self.assertEqual(load_revision(ledger, issued.revision_id).observations[0].upper_ms, Fraction(1, 10))
            self.assertNotIn('"X"', canonical_envelope(fetched))

    def test_reopen_issue(self):
        with open_station(self.path, 'north') as (ledger, publisher):
            issued = stage_revision(ledger, publisher, self.case, self.case['north'])
            revision = load_revision(ledger, issued.revision_id)
        with open_station(self.path, 'north') as (ledger, publisher):
            ledger.initialize()
            publisher.initialize()
            self.assertEqual(load_revision(ledger, issued.revision_id), revision)
            self.assertEqual(publisher.get_issued_station(issued.issue_id), issued)
            self.assertEqual(publisher.publish(issued.revision_id, ()).body['candidates'], [])
            with self.assertRaisesRegex(ValueError, 'retained'):
                publisher.publish(issued.revision_id, ['C'])
            with self.assertRaises(KeyError):
                publisher.publish(999)

    def test_unknown_voucher(self):
        with open_station(self.path, 'north') as (ledger, publisher):
            issued = stage_revision(ledger, publisher, self.case, self.case['north'])
            with self.assertRaisesRegex(ValueError, 'unknown voucher'):
                save_revision(ledger, self.case['round_id'], [Observation('U', 'V', 1, 'unknown')], issued.revision_id)
            with self.assertRaises(KeyError):
                load_revision(ledger, issued.revision_id + 1)
            self.assertEqual(publisher.publish(issued.revision_id).revision_id, issued.revision_id)

    def test_invalid_bound(self):
        with open_station(self.path, 'north') as (ledger, publisher):
            issued = stage_revision(ledger, publisher, self.case, self.case['north'])
            for bad in (None, '1/0', '', 'infinity', 0.1, False):
                with self.subTest(bound=bad), self.assertRaises(ValueError):
                    save_revision(ledger, self.case['round_id'], [Observation('U', 'V', bad, 'A')], issued.revision_id)
            with self.assertRaises(KeyError):
                load_revision(ledger, issued.revision_id + 1)
            self.assertEqual(publisher.publish(issued.revision_id).body['conditions'], issued.body['conditions'])

    def test_parent_round(self):
        with open_station(self.path, 'north') as (ledger, publisher):
            issued = stage_revision(ledger, publisher, self.case, self.case['north'])
            register_round(ledger, RoundSpec('other', ('U', 'V')), [Voucher('A')])
            with self.assertRaisesRegex(ValueError, 'another round'):
                save_revision(ledger, 'other', [Observation('U', 'V', 2, 'A')], issued.revision_id)
            with self.assertRaisesRegex(ValueError, 'different specification'):
                register_round(ledger, RoundSpec('other', ('U', 'W')), [Voucher('A')])
            with self.assertRaises(KeyError):
                load_revision(ledger, issued.revision_id + 1)
            self.assertEqual(publisher.publish(issued.revision_id).revision_id, issued.revision_id)
