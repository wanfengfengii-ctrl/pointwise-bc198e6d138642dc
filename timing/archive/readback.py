from dataclasses import dataclass

from timing.archive.archive_store import ArchiveStore
from timing.archive.reports import CommitReceipt, Report, decode_report
from timing.intake.lookup import StationProvenance
from timing.source.rounds import require_number


@dataclass(frozen=True)
class ReportReadback:
    report: Report
    receipt: CommitReceipt
    sources: tuple[StationProvenance, StationProvenance]


def _read_row(row, number: int, kind: str) -> ReportReadback:
    if row is None:
        raise KeyError(f'unknown {kind} {number}')
    report_id, content, receipt_id, left_id, right_id = row
    report = decode_report(report_id, content)
    result = report.draft.result
    if result.request.receipt_ids != (left_id, right_id):
        raise ValueError('archive source links do not match the report snapshot')
    return ReportReadback(report, CommitReceipt(receipt_id, report_id), result.sources)


def read_by_report(archive: ArchiveStore, report_id: int) -> ReportReadback:
    number = require_number(report_id, 'report number')
    return _read_row(archive.fetch_by_report(number), number, 'report')


def read_by_receipt(archive: ArchiveStore, receipt_id: int) -> ReportReadback:
    number = require_number(receipt_id, 'commit receipt number')
    return _read_row(archive.fetch_by_receipt(number), number, 'commit receipt')
