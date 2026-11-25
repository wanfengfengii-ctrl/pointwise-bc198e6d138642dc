import json
import sqlite3
from contextlib import closing, contextmanager
from fractions import Fraction
from pathlib import Path

from demo import open_center, open_station, stage_revision
from tests.support import CenterTestCase
from timing.archive.tick_readback import read_tick_window
from timing.intake.receipts import accept_station, accept_station_v2
from timing.intake.v2_envelope import canonical_v2_envelope
from timing.issue.publish import StationPublisher
from timing.issue.tick import PhaseInterval, build_tick_qualification, decode_tick_body
from timing.review.tick_window import sign_tick_window
from timing.source.ledger import SourceLedger
from timing.source.observations import Observation
from timing.source.revisions import load_revision, register_round, save_revision
from timing.source.rounds import RoundSpec
from timing.source.vouchers import Voucher

TICK_CASE = Path(__file__).resolve().parent.parent / 'samples' / 'tick_window.json'
SHIFT_CASE = Path(__file__).resolve().parent.parent / 'samples' / 'shift.json'


def load_tick_case():
    return json.loads(TICK_CASE.read_text(encoding='utf-8'))


@contextmanager
def reopen_station(path, station):
    with closing(sqlite3.connect(path)) as connection:
        ledger = SourceLedger(connection, station)
        ledger.initialize()
        publisher = StationPublisher(ledger)
        publisher.initialize()
        yield ledger, publisher


class TickIssueTests(CenterTestCase):
    def _station(self, name='north'):
        return self.enterContext(open_station(self.root / f'{name}.sqlite', name))

    def _revision(self, publisher, ledger, case, rows, parent=None):
        register_round(
            ledger, RoundSpec(case['round_id'], tuple(case['anchors'])),
            [Voucher(*row) for row in case['vouchers']],
        )
        revision_id = save_revision(
            ledger, case['round_id'], (Observation(*row) for row in rows), parent
        )
        revision = load_revision(ledger, revision_id)
        return revision, publisher.publish_v2(revision_id, Fraction(1))

    def test_aligned_and_half_qualifications(self):
        case = load_tick_case()
        ledger, publisher = self._station()
        aligned, envelope = self._revision(
            publisher, ledger, case, case['revisions']['north-aligned']['rows']
        )
        qualification = build_tick_qualification(aligned, Fraction(1), envelope.issue_id)
        self.assertTrue(qualification.feasible)
        self.assertEqual(qualification.phases, (PhaseInterval(Fraction(0), Fraction(0)),))
        self.assertTrue(qualification.contains(Fraction(0)))
        self.assertFalse(qualification.contains(Fraction(1, 2)))

        half_revision, half_envelope = self._revision(
            publisher, ledger, case, case['revisions']['north-half']['rows'],
            envelope.revision_id,
        )
        half = build_tick_qualification(half_revision, Fraction(1), half_envelope.issue_id)
        self.assertEqual(half.phases, (PhaseInterval(Fraction(1, 2), Fraction(1, 2)),))
        self.assertTrue(half.contains(Fraction(1, 2)))
        self.assertFalse(half.contains(Fraction(1, 4)))
        self.assertTrue(half.contains(Fraction(3, 2)))

    def test_isolated_private_component_conflicts(self):
        case = load_tick_case()
        ledger, publisher = self._station()
        register_round(
            ledger, RoundSpec(case['round_id'], tuple(case['anchors'])),
            [Voucher(*row) for row in case['vouchers']],
        )
        revision_id = save_revision(
            ledger, case['round_id'],
            (Observation(*row) for row in case['revisions']['north-isolated']['rows']),
        )
        qualification = build_tick_qualification(load_revision(ledger, revision_id), Fraction(1))
        self.assertFalse(qualification.feasible)
        self.assertIsNone(qualification.phases)
        self.assertIsNone(qualification.bounds)

    def test_publish_v2_keeps_private_names_at_station_only(self):
        case = load_tick_case()
        ledger, publisher = self._station()
        _, envelope = self._revision(
            publisher, ledger, case, case['revisions']['north-half']['rows']
        )
        text = canonical_v2_envelope(envelope)
        self.assertEqual(envelope.version, 2)
        self.assertNotIn('private-N', text)
        self.assertEqual(publisher.get_issued_v2(envelope.issue_id), envelope)
        with self.assertRaises(KeyError):
            publisher.get_issued_v2(999)

    def test_invalid_tick_rejected(self):
        case = load_tick_case()
        ledger, publisher = self._station()
        register_round(
            ledger, RoundSpec(case['round_id'], tuple(case['anchors'])),
            [Voucher(*row) for row in case['vouchers']],
        )
        revision_id = save_revision(
            ledger, case['round_id'],
            (Observation(*row) for row in case['revisions']['north-half']['rows']),
        )
        for bad in (0, -1, '1/0', 0.25, False, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                publisher.publish_v2(revision_id, bad)

    def test_shared_issue_numbering_with_v1(self):
        case = load_tick_case()
        ledger, publisher = self._station()
        register_round(
            ledger, RoundSpec(case['round_id'], tuple(case['anchors'])),
            [Voucher(*row) for row in case['vouchers']],
        )
        first = save_revision(
            ledger, case['round_id'],
            (Observation(*row) for row in case['revisions']['north-aligned']['rows']),
        )
        second = save_revision(
            ledger, case['round_id'],
            (Observation(*row) for row in case['revisions']['north-half']['rows']), first,
        )
        v2 = publisher.publish_v2(first, Fraction(1))
        v1 = publisher.publish(second)
        self.assertEqual(v1.issue_id, v2.issue_id + 1)
        self.assertEqual(publisher.get_issued_v2(v2.issue_id).version, 2)
        self.assertEqual(publisher.get_issued_station(v1.issue_id).version, 1)


class PhaseCircleTests(CenterTestCase):
    def test_origin_excluding_wrap_round_trip(self):
        section = PhaseInterval(Fraction(2, 3), Fraction(0), False)
        self.assertTrue(section.wraps)
        self.assertFalse(section.includes_origin)
        payload = section.to_payload()
        self.assertEqual(payload, [[2, 3], [0, 1], False])
        self.assertEqual(PhaseInterval.from_payload(payload), section)
        ordinary = PhaseInterval.from_payload([[0, 1], [1, 2]])
        self.assertTrue(ordinary.includes_origin)
        for malformed in (
            [[1, 2], [0, 1], 'no'],
            [[1, 2]],
            [[2, 1], [1, 2]],
            [[0, 1], [1, 0], False],
        ):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                PhaseInterval.from_payload(malformed)

    def test_negative_beat_phase_and_wrapping_contains(self):
        # A wrapping [2/3, 1) section excluding the origin admits phase 3/4
        # for a negative d while rejecting the exact-beat phase 0.
        section = PhaseInterval(Fraction(2, 3), Fraction(0), False)
        qualification = TickQualificationShim(section, Fraction(1))
        self.assertTrue(qualification.contains(Fraction(-1, 4)))
        self.assertFalse(qualification.contains(Fraction(1)))
        self.assertFalse(qualification.contains(Fraction(0)))
        body = decode_tick_body(
            json.loads(json.dumps(encode_tick_body_shim(qualification)))
        )
        self.assertEqual(body, qualification)

    def test_wrapping_origin_included_section(self):
        section = PhaseInterval(Fraction(2, 3), Fraction(1, 3), True)
        qualification = TickQualificationShim(section, Fraction(1))
        # Phases 5/6 (upper tail), 0 and 1/4 (origin side) are all feasible.
        self.assertTrue(qualification.contains(Fraction(5, 6)))
        self.assertTrue(qualification.contains(Fraction(0)))
        self.assertTrue(qualification.contains(Fraction(1, 4)))
        self.assertFalse(qualification.contains(Fraction(1, 2)))


def TickQualificationShim(section, tick=Fraction(3, 2)):
    from timing.issue.intervals import TimeInterval
    from timing.issue.tick import TickQualification

    return TickQualification(
        'station', 'round', 1, 1, ('U', 'V'), tick, True,
        TimeInterval(None, None), (section,),
    )


def encode_tick_body_shim(qualification):
    from timing.issue.tick import encode_tick_body

    return encode_tick_body(qualification)


class TickIntakeTests(CenterTestCase):
    def setUp(self):
        super().setUp()
        self.case = load_tick_case()
        self.envelopes = {}
        with open_station(self.root / 'north.sqlite', 'north') as (ledger, publisher):
            register_round(
                ledger, RoundSpec(self.case['round_id'], tuple(self.case['anchors'])),
                [Voucher(*row) for row in self.case['vouchers']],
            )
            parent = None
            for name in ('north-aligned', 'north-half'):
                revision_id = save_revision(
                    ledger, self.case['round_id'],
                    (Observation(*row) for row in self.case['revisions'][name]['rows']),
                    parent,
                )
                self.envelopes[name] = publisher.publish_v2(revision_id, Fraction(1))
                parent = revision_id

    def test_v2_replay_and_conflict(self):
        envelope = self.envelopes['north-half']
        first = accept_station_v2(self.intake, canonical_v2_envelope(envelope))
        replay = accept_station_v2(self.intake, canonical_v2_envelope(envelope))
        self.assertEqual(replay.receipt_id, first.receipt_id)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.replay_count, 1)
        tampered = json.loads(canonical_v2_envelope(envelope))
        tampered['body']['bounds'] = {'lower': [1, 1], 'upper': None}
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            accept_station_v2(self.intake, json.dumps(tampered))

    def test_malformed_v2_rejected(self):
        raw = canonical_v2_envelope(self.envelopes['north-aligned'])
        wrong_version = json.loads(raw)
        wrong_version['version'] = 1
        bad_tick = json.loads(raw)
        bad_tick['body']['tick_ms'] = [0, 1]
        conflict_with_phases = json.loads(raw)
        conflict_with_phases['body']['status'] = 'conflict'
        identity_mismatch = json.loads(raw)
        identity_mismatch['body']['revision_id'] += 1
        for payload in (wrong_version, bad_tick, conflict_with_phases, identity_mismatch):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                accept_station_v2(self.intake, json.dumps(payload))
        self.assertEqual(
            self.intake.connection.execute('SELECT count(*) FROM intake_receipts').fetchone()[0], 0
        )

    def test_v1_documents_still_use_the_v1_path(self):
        case = json.loads(SHIFT_CASE.read_text(encoding='utf-8'))
        with open_station(self.root / 'south.sqlite', 'south') as (ledger, publisher):
            v1 = stage_revision(ledger, publisher, case, case['south'])
        receipt = accept_station(self.intake, v1)
        self.assertTrue(receipt.receipt_id > 0)


class TickWindowSigningTests(CenterTestCase):
    def setUp(self):
        super().setUp()
        self.case = load_tick_case()
        self.receipts = self._publish_all()

    def _publish_all(self):
        receipts = {}
        issues = {}
        paths = {}
        for name, spec in self.case['revisions'].items():
            station = spec['station']
            path = self.root / f'{station}.sqlite'
            if station not in paths:
                paths[station] = path
                context = open_station(path, station)
            else:
                context = reopen_station(path, station)
            with context as (ledger, publisher):
                register_round(
                    ledger, RoundSpec(self.case['round_id'], tuple(self.case['anchors'])),
                    [Voucher(*row) for row in self.case['vouchers']],
                )
                parent = issues[spec['parent']].revision_id if 'parent' in spec else None
                revision_id = save_revision(
                    ledger, self.case['round_id'],
                    (Observation(*row) for row in spec['rows']), parent,
                )
                envelope = publisher.publish_v2(revision_id, Fraction(spec['tick_ms']))
                issues[name] = envelope
                receipts[name] = accept_station_v2(
                    self.intake, canonical_v2_envelope(envelope)
                ).receipt_id
        return receipts

    def test_all_sample_orders_and_windows(self):
        for order in self.case['orders']:
            pair = tuple(self.receipts[name] for name in order['revisions'])
            for lo_ms, hi_ms, expected_text in order['windows']:
                report = sign_tick_window(self.archive, pair, lo_ms, hi_ms)
                expected = None if expected_text is None else Fraction(expected_text)
                self.assertEqual(report.earliest_ms, expected)
                self.assertEqual(tuple(s.receipt_id for s in report.sources), pair)
                stored = read_tick_window(self.archive, report.report_id)
                self.assertEqual(stored.earliest_ms, expected)
                self.assertEqual(stored.commit_receipt_id, report.commit_receipt_id)
                self.assertEqual(stored.lo_ms, Fraction(lo_ms))
                self.assertEqual(stored.hi_ms, Fraction(hi_ms))

    def test_pairing_and_window_rejections(self):
        north = self.receipts['north-half']
        south = self.receipts['south-free']
        with self.assertRaises(ValueError):
            sign_tick_window(self.archive, (north, north), '0', '1')
        with self.assertRaises(KeyError):
            sign_tick_window(self.archive, (north, 999), '0', '1')
        with self.assertRaises(ValueError):
            sign_tick_window(self.archive, (north,), '0', '1')
        for lo_ms, hi_ms in ((-1, 1), (1, 0), ('1/0', 1)):
            with self.assertRaises(ValueError):
                sign_tick_window(self.archive, (north, south), lo_ms, hi_ms)

    def test_atomic_rollback_on_write_failure(self):
        pair = (self.receipts['north-half'], self.receipts['south-free'])
        connection = self.archive.connection
        connection.executescript('''
            CREATE TRIGGER fail_tick BEFORE INSERT ON tick_window_commit_receipts
            BEGIN SELECT RAISE(ABORT, 'tick commit unavailable'); END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'tick commit unavailable'):
            sign_tick_window(self.archive, pair, '1/4', '3/4')
        counts = connection.execute('''
            SELECT (SELECT count(*) FROM tick_window_reports),
                   (SELECT count(*) FROM tick_window_parents),
                   (SELECT count(*) FROM tick_window_commit_receipts)
        ''').fetchone()
        self.assertEqual(tuple(counts), (0, 0, 0))
        connection.execute('DROP TRIGGER fail_tick')
        report = sign_tick_window(self.archive, pair, '1/4', '3/4')
        self.assertEqual(report.earliest_ms, Fraction(1, 2))

    def test_reopen_center_readback(self):
        pair = (self.receipts['north-half'], self.receipts['south-free'])
        report = sign_tick_window(self.archive, pair, '1/4', '3/4')
        self.archive.connection.close()
        with open_center(self.center_path) as (intake, archive):
            intake.initialize()
            archive.initialize()
            stored = read_tick_window(archive, report.report_id)
            self.assertEqual(stored.earliest_ms, Fraction(1, 2))
            self.assertEqual([s.station_id for s in stored.sources], ['north', 'south'])
        with open_center(self.center_path) as (_, archive):
            archive.initialize()
            with self.assertRaisesRegex(KeyError, 'unknown tick window report'):
                read_tick_window(archive, report.report_id + 100)
