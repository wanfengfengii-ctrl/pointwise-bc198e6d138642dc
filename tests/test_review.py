from demo import load_case, open_station, stage_revision
from tests.support import CenterTestCase, fixed_station, interval
from timing.archive.readback import read_by_report
from timing.intake.checks import verify_station
from timing.intake.receipts import accept_station
from timing.review.joint import review_pair


class ReviewTests(CenterTestCase):
    def test_alternative_bound(self):
        issues, ids = self.stage_pair()
        evidence = verify_station(issues[0]).evidence
        self.assertEqual(evidence.conditions[1].voucher_id, 'A')
        self.assertEqual(evidence.conditions[1].interval, interval(None, 1))
        self.assertNotIn('private-N', repr(issues[0].body))
        for station in ('north', 'south'):
            (self.root / f'{station}.sqlite').unlink()
        report, _ = self.sign(self.request(ids))
        retrieved = read_by_report(self.archive, report.report_id)
        self.assert_outcomes(retrieved.report.draft.result, ((None, None), ('A', interval(1, 1)), ('B', None)))
        self.assertEqual(tuple(source.receipt_id for source in retrieved.sources), ids)

    def test_voucher_group(self):
        case = load_case('shift')
        case['north'].append(['U', 'V', '1/2', 'A'])
        case['south'].append(['V', 'U', -2, 'A'])
        issues, ids = self.stage_pair(case)
        self.assertEqual(verify_station(issues[0]).evidence.conditions[1].interval, interval(None, 1))
        self.assertEqual(verify_station(issues[1]).evidence.conditions[1].interval, interval(1, None))
        report, _ = self.sign(self.request(ids))
        self.assert_outcomes(report.draft.result, ((None, None), ('A', interval(1, 1)), ('B', None)))

    def test_request_order(self):
        _, ids = self.stage_pair()
        report, _ = self.sign(self.request(ids[::-1], ('B', 'A', 'B')))
        retrieved = read_by_report(self.archive, report.report_id)
        self.assert_outcomes(
            retrieved.report.draft.result, ((None, None), ('B', None), ('A', interval(1, 1)), ('B', None))
        )
        self.assertEqual(tuple(source.receipt_id for source in retrieved.sources), ids[::-1])

    def test_crossed_vouchers(self):
        at_least_one = {'lower': [1, 1], 'upper': None}
        at_most_zero = {'lower': None, 'upper': [0, 1]}
        north = fixed_station('fixed-north', (None, at_least_one, at_most_zero))
        south = fixed_station('fixed-south', (None, at_most_zero, at_least_one))
        ids = tuple(accept_station(self.intake, item).receipt_id for item in (north, south))
        result = review_pair(self.intake, self.request(ids))
        self.assert_outcomes(result, ((None, None), ('A', None), ('B', None)))

    def test_crossed_report(self):
        _, ids = self.stage_pair(load_case('crossed'))
        for station in ('north', 'south'):
            (self.root / f'{station}.sqlite').unlink()
        report, receipt = self.sign(self.request(ids))
        retrieved = read_by_report(self.archive, report.report_id)
        self.assert_outcomes(retrieved.report.draft.result, ((None, None), ('A', None), ('B', None)))
        self.assertEqual(retrieved.receipt, receipt)
        self.assertEqual(tuple(source.receipt_id for source in retrieved.sources), ids)

    def test_unbounded_and_private_conflict(self):
        case = load_case('shift')
        case['north'] = []
        issues, ids = self.stage_pair(case)
        report, _ = self.sign(self.request(ids, ()))
        self.assert_outcomes(report.draft.result, ((None, interval(1, None)),))
        private_rows = [['P', 'Q', 0, 'A'], ['Q', 'P', -1, 'A']]
        with open_station(self.root / 'north.sqlite', 'north') as (ledger, publisher):
            changed = stage_revision(ledger, publisher, case, private_rows, issues[0].revision_id)
            changed_id = accept_station(self.intake, changed).receipt_id
        private_evidence = verify_station(changed).evidence
        self.assertIsNone(private_evidence.conditions[0].interval)
        self.assertEqual(private_evidence.conditions[1].interval, interval(None, None))
        changed_report, _ = self.sign(self.request((changed_id, ids[1])))
        self.assert_outcomes(changed_report.draft.result, ((None, None), ('A', interval(1, None)), ('B', None)))

    def test_anchor_reversal(self):
        case = load_case('shift')
        case['north'] = []
        _, ids = self.stage_pair(case)
        report, _ = self.sign(self.request(ids, (), ('V', 'U')))
        self.assert_outcomes(report.draft.result, ((None, interval(None, -1)),))

    def test_wrong_round(self):
        first = load_case('shift')
        first['north'] = []
        _, original_ids = self.stage_pair(first)
        second = load_case('shift')
        second['round_id'] = 'another-round'
        with open_station(self.root / 'south.sqlite', 'south') as (ledger, publisher):
            issued = stage_revision(ledger, publisher, second, second['south'])
            other = accept_station(self.intake, issued).receipt_id
        with self.assertRaisesRegex(ValueError, 'different rounds'):
            self.sign(self.request((original_ids[0], other)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_unknown_receipt(self):
        _, ids = self.stage_pair()
        with self.assertRaisesRegex(KeyError, 'unknown intake receipt'):
            self.sign(self.request((ids[0], 999)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_anchor_mismatch(self):
        _, ids = self.stage_pair()
        with self.assertRaisesRegex(ValueError, 'public anchors'):
            self.sign(self.request(ids, anchors=('U', 'W')))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_unknown_candidate(self):
        _, ids = self.stage_pair()
        for candidate in ('unknown', 'C'):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, 'unknown or not covered'):
                self.sign(self.request(ids, (candidate,)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_uncovered_known_candidate(self):
        issues, ids = self.stage_pair()
        with open_station(self.root / 'north.sqlite', 'north') as (_, publisher):
            subset = publisher.publish(issues[0].revision_id, ['B'])
            subset_id = accept_station(self.intake, subset).receipt_id
        with self.assertRaisesRegex(ValueError, 'not covered'):
            self.sign(self.request((subset_id, ids[1]), ('A',)))
        self.assertEqual(self.archive_counts(), (0, 0, 0))
        report, _ = self.sign(self.request((subset_id, ids[1]), ('B',)))
        self.assert_outcomes(report.draft.result, ((None, None), ('B', None)))
