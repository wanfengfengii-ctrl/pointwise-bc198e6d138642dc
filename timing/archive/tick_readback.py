from timing.archive.archive_store import ArchiveStore
from timing.review.tick_window import TickWindowReport, decode_tick_window_report
from timing.source.rounds import require_number


def read_tick_window(archive: ArchiveStore, report_id: int) -> TickWindowReport:
    number = require_number(report_id, 'tick window report number')
    row = archive.fetch_tick_window_by_report(number)
    if row is None:
        raise KeyError(f'unknown tick window report {number}')
    stored_id, content, receipt_id, left_id, right_id = row
    report = decode_tick_window_report(stored_id, content)
    if tuple(source.receipt_id for source in report.sources) != (left_id, right_id):
        raise ValueError('archive source links do not match the tick window snapshot')
    return TickWindowReport(
        report.report_id, receipt_id, report.lo_ms, report.hi_ms,
        report.earliest_ms, report.sources,
    )
