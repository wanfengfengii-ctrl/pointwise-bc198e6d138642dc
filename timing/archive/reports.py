import json
from dataclasses import asdict, dataclass

from timing.intake.lookup import StationProvenance
from timing.issue.intervals import TimeInterval
from timing.review.request import ReviewRequest
from timing.review.result import ConditionOutcome, ReviewResult
from timing.source.rounds import require_identifier, require_number


@dataclass(frozen=True)
class ReportDraft:
    result: ReviewResult

    def __post_init__(self) -> None:
        if not isinstance(self.result, ReviewResult):
            raise ValueError('a report draft requires a reviewed result')


@dataclass(frozen=True)
class Report:
    report_id: int
    draft: ReportDraft


@dataclass(frozen=True)
class CommitReceipt:
    receipt_id: int
    report_id: int


def build_report_draft(result: ReviewResult) -> ReportDraft:
    return ReportDraft(result)


def encode_report(draft: ReportDraft) -> str:
    result = draft.result
    data = {
        'request': asdict(result.request),
        'sources': [asdict(source) for source in result.sources],
        'outcomes': [
            {
                'voucher_id': item.voucher_id,
                'status': item.status,
                'interval': None if item.interval is None else item.interval.to_payload(),
            }
            for item in result.outcomes
        ],
    }
    return json.dumps(data, ensure_ascii=True, separators=(',', ':'), sort_keys=True)


def _decode_source(data: dict) -> StationProvenance:
    return StationProvenance(
        require_number(data['receipt_id'], 'archived intake number'),
        require_identifier(data['station_id'], 'archived station identity'),
        require_number(data['issue_id'], 'archived issue number'),
        require_identifier(data['round_id'], 'archived round identity'),
        require_number(data['revision_id'], 'archived revision number'),
    )


def _decode_outcome(data: dict) -> ConditionOutcome:
    voucher = data['voucher_id']
    if voucher is not None:
        voucher = require_identifier(voucher, 'archived candidate')
    if data['status'] == 'conflict' and data['interval'] is None:
        return ConditionOutcome(voucher, None)
    if data['status'] == 'feasible':
        return ConditionOutcome(voucher, TimeInterval.from_payload(data['interval']))
    raise ValueError('invalid archived condition status')


def decode_report(report_id: int, content: str) -> Report:
    number = require_number(report_id, 'report number')
    data = json.loads(content)
    request = ReviewRequest(**data['request'])
    sources = tuple(_decode_source(source) for source in data['sources'])
    outcomes = tuple(_decode_outcome(outcome) for outcome in data['outcomes'])
    return Report(number, ReportDraft(ReviewResult(request, sources, outcomes)))
