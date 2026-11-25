import sqlite3
from contextlib import closing
from dataclasses import replace
from fractions import Fraction

from demo import load_case, open_center, open_station, stage_revision
from tests.support import CenterTestCase, interval
from timing.archive.commit import commit_report
from timing.archive.export import export_handover
from timing.archive.readback import read_by_receipt, read_by_report
from timing.archive.reports import build_report_draft
from timing.intake.lookup import get_received_station
from timing.intake.receipts import accept_station
from timing.review.joint import review_pair
from timing.source.revisions import load_revision


class ArchiveTests(CenterTestCase):
    def test_receipt_commit_failure(self):
        _, ids = self.stage_pair()
        draft = build_report_draft(review_pair(self.intake, self.request(ids)))
        connection = self.archive.connection
        connection.executescript('''
            CREATE TRIGGER fail_signing BEFORE INSERT ON commit_receipts
            BEGIN
                SELECT CASE WHEN
                    (SELECT count(*) FROM report_parents WHERE report_id = NEW.report_id) = 2
                    AND EXISTS (SELECT 1 FROM reports WHERE report_id = NEW.report_id)
                    THEN RAISE(ABORT, 'receipt storage unavailable after report and parents')
                    ELSE RAISE(ABORT, 'unexpected signing stage') END;
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'unavailable after report and parents'):
            commit_report(self.archive, draft)
        self.assertEqual(self.archive_counts(), (0, 0, 0))
        with closing(sqlite3.connect(self.center_path)) as reader:
            for table in ('reports', 'report_parents', 'commit_receipts'):
                self.assertEqual(reader.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        with self.assertRaises(KeyError):
            read_by_report(self.archive, 1)
        connection.execute('DROP TRIGGER fail_signing')
        report, receipt = commit_report(self.archive, draft)
        self.assertEqual(self.archive_counts(), (1, 2, 1))
        self.assertEqual(read_by_receipt(self.archive, receipt.receipt_id).report, report)

    def test_revision_readback(self):
        case = load_case('shift')
        issues, ids = self.stage_pair(case)
        old_report, old_receipt = self.sign(self.request(ids))
        with open_station(self.root / 'north.sqlite', 'north') as (ledger, publisher):
            correction = stage_revision(ledger, publisher, case, case['north_correction'], issues[0].revision_id)
            stored = load_revision(ledger, correction.revision_id)
            self.assertEqual(stored.parent_id, issues[0].revision_id)
            self.assertEqual(stored.observations[2].upper_ms, Fraction(7, 6))
            corrected_id = accept_station(self.intake, correction).receipt_id
        new_ids = (corrected_id, ids[1])
        new_report, new_receipt = self.sign(self.request(new_ids))
        self.archive.connection.close()
        with open_center(self.center_path) as (intake, archive):
            intake.initialize()
            archive.initialize()
            old = read_by_report(archive, old_report.report_id)
            new = read_by_receipt(archive, new_receipt.receipt_id)
            self.assertEqual(old, read_by_receipt(archive, old_receipt.receipt_id))
            self.assertEqual(new, read_by_report(archive, new_report.report_id))
            self.assertEqual((old.report, old.receipt), (old_report, old_receipt))
            self.assertEqual((new.report, new.receipt), (new_report, new_receipt))
            self.assertEqual(tuple(source.receipt_id for source in old.sources), ids)
            self.assertEqual(tuple(source.receipt_id for source in new.sources), new_ids)
            self.assertEqual(old.sources[0].revision_id, issues[0].revision_id)
            self.assertEqual(new.sources[0].revision_id, correction.revision_id)
            self.assertEqual(new.sources[1], old.sources[1])
            self.assertEqual(get_received_station(intake, ids[0]).station.envelope, issues[0])
            self.assertEqual(get_received_station(intake, corrected_id).station.envelope, correction)
        self.assert_outcomes(old.report.draft.result, ((None, None), ('A', interval(1, 1)), ('B', None)))
        self.assert_outcomes(new.report.draft.result, ((None, None), ('A', interval(1, Fraction(3, 2))), ('B', None)))
        self.assertIn('撤 A [1,1] ms', export_handover(old))
        self.assertIn('撤 A [1,3/2] ms', export_handover(new))

    def test_unknown_number(self):
        _, ids = self.stage_pair()
        report, receipt = self.sign(self.request(ids))
        with self.assertRaisesRegex(KeyError, 'unknown report'):
            read_by_report(self.archive, report.report_id + 1)
        with self.assertRaisesRegex(KeyError, 'unknown commit receipt'):
            read_by_receipt(self.archive, receipt.receipt_id + 1)
        self.assertEqual(self.archive_counts(), (1, 2, 1))

    def test_inconsistent_draft_provenance(self):
        _, ids = self.stage_pair()
        result = review_pair(self.intake, self.request(ids))
        left, right = result.sources
        inconsistent = replace(result, sources=(replace(left, issue_id=left.issue_id + 1), right))
        with self.assertRaisesRegex(ValueError, 'draft provenance'):
            commit_report(self.archive, build_report_draft(inconsistent))
        self.assertEqual(self.archive_counts(), (0, 0, 0))
