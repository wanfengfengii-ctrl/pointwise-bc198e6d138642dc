import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from demo import capture_pair, load_case, open_center, sign
from timing.issue.intervals import TimeInterval
from timing.review.request import ReviewRequest


class CenterTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory(prefix='timing-test-')))
        self.center_path = self.root / 'center.sqlite'
        self.intake, self.archive = self.enterContext(open_center(self.center_path))

    def stage_pair(self, case=None):
        if case is None:
            case = load_case('shift')
        return capture_pair(self.root, self.intake, case)

    def request(self, ids, candidates=('A', 'B'), anchors=('U', 'V')):
        return ReviewRequest(ids, anchors, candidates)

    def sign(self, request):
        return sign(self.archive, self.intake, request)

    def archive_counts(self):
        row = self.archive.connection.execute('''
            SELECT (SELECT count(*) FROM reports), (SELECT count(*) FROM report_parents),
                   (SELECT count(*) FROM commit_receipts)
        ''').fetchone()
        return tuple(row)

    def assert_outcomes(self, result, expected):
        self.assertEqual(tuple((item.voucher_id, item.interval) for item in result.outcomes), expected)


def interval(lower, upper):
    return TimeInterval(lower, upper)


def fixed_station(station, conditions):
    """Assemble a wire fixture directly, independent of source and publication."""
    identity = {'station_id': station, 'issue_id': 1, 'round_id': 'fixed-round', 'revision_id': 1}
    body = {
        **identity,
        'anchors': ['U', 'V'],
        'candidates': ['A', 'B'],
        'conditions': [
            {'voucher_id': voucher, 'status': 'conflict' if limits is None else 'feasible', 'interval': limits}
            for voucher, limits in zip((None, 'A', 'B'), conditions, strict=True)
        ],
    }
    return json.dumps({**identity, 'version': 1, 'body': body})
