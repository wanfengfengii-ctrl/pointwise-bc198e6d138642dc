from dataclasses import dataclass

from timing.issue.evidence import ConditionEvidence, StationEvidence
from timing.review.request import ResolvedReviewRequest


@dataclass(frozen=True)
class PairedCondition:
    voucher_id: str | None
    left: ConditionEvidence
    right: ConditionEvidence


def _oriented_conditions(
    evidence: StationEvidence, anchors: tuple[str, str]
) -> dict[str | None, ConditionEvidence]:
    if evidence.anchors == anchors:
        return {condition.voucher_id: condition for condition in evidence.conditions}
    return {
        condition.voucher_id: ConditionEvidence(
            condition.voucher_id,
            None if condition.interval is None else condition.interval.reversed(),
        )
        for condition in evidence.conditions
    }


def bind_conditions(resolved: ResolvedReviewRequest) -> tuple[PairedCondition, ...]:
    request = resolved.request
    left = _oriented_conditions(resolved.left.station.evidence, request.anchors)
    right = _oriented_conditions(resolved.right.station.evidence, request.anchors)
    return tuple(
        PairedCondition(candidate, left[candidate], right[candidate])
        for candidate in (None, *request.candidates)
    )
