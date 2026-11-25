from timing.archive.archive_store import ArchiveStore
from timing.archive.reports import CommitReceipt, Report, ReportDraft, encode_report
from timing.intake.receipt_store import ReceiptStore
from timing.review.request import resolve_review_request


def commit_report(archive: ArchiveStore, draft: ReportDraft) -> tuple[Report, CommitReceipt]:
    if not isinstance(draft, ReportDraft):
        raise ValueError('a ReportDraft is required')
    db = archive.connection
    result = draft.result
    content = encode_report(draft)
    db.execute('BEGIN IMMEDIATE')
    with db:
        resolved = resolve_review_request(ReceiptStore(db), result.request)
        sources = (resolved.left.provenance, resolved.right.provenance)
        if sources != result.sources:
            raise ValueError('draft provenance does not match the selected intake receipts')
        report_id = archive.insert_report(content, result.request.receipt_ids)
        receipt_id = archive.insert_receipt(report_id)
    return Report(report_id, draft), CommitReceipt(receipt_id, report_id)
