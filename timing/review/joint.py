from timing.intake.receipt_store import ReceiptStore
from timing.issue.intervals import TimeInterval
from timing.review.conditions import bind_conditions
from timing.review.request import ReviewRequest, resolve_review_request
from timing.review.result import ConditionOutcome, ReviewResult, assemble_review_result


def intersect_intervals(left: TimeInterval | None, right: TimeInterval | None) -> TimeInterval | None:
    if left is None or right is None:
        return None
    lower = max((endpoint for endpoint in (left.lower, right.lower) if endpoint is not None), default=None)
    upper = min((endpoint for endpoint in (left.upper, right.upper) if endpoint is not None), default=None)
    if lower is not None and upper is not None and lower > upper:
        return None
    return TimeInterval(lower, upper)


def review_pair(store: ReceiptStore, request: ReviewRequest) -> ReviewResult:
    resolved = resolve_review_request(store, request)
    outcomes = (
        ConditionOutcome(pair.voucher_id, intersect_intervals(pair.left.interval, pair.right.interval))
        for pair in bind_conditions(resolved)
    )
    return assemble_review_result(resolved, outcomes)
