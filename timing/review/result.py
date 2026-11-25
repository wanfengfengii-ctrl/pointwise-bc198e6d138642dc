from collections.abc import Iterable
from dataclasses import dataclass

from timing.intake.lookup import StationProvenance
from timing.issue.intervals import TimeInterval
from timing.review.request import ResolvedReviewRequest, ReviewRequest


@dataclass(frozen=True)
class ConditionOutcome:
    voucher_id: str | None
    interval: TimeInterval | None

    @property
    def status(self) -> str:
        return 'conflict' if self.interval is None else 'feasible'


@dataclass(frozen=True)
class ReviewResult:
    request: ReviewRequest
    sources: tuple[StationProvenance, StationProvenance]
    outcomes: tuple[ConditionOutcome, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, ReviewRequest):
            raise ValueError('review result must contain its original request')
        if not isinstance(self.sources, tuple) or len(self.sources) != 2:
            raise ValueError('review result must contain two ordered sources')
        if any(not isinstance(source, StationProvenance) for source in self.sources):
            raise ValueError('invalid provenance in review result')
        left, right = self.sources
        if (left.receipt_id, right.receipt_id) != self.request.receipt_ids:
            raise ValueError('review provenance does not match the original receipt order')
        if left.station_id == right.station_id or left.round_id != right.round_id:
            raise ValueError('review provenance must represent two stations of the same round')
        if not isinstance(self.outcomes, tuple) or any(
            not isinstance(item, ConditionOutcome)
            or (item.interval is not None and not isinstance(item.interval, TimeInterval))
            for item in self.outcomes
        ):
            raise ValueError('invalid review outcomes')
        if tuple(item.voucher_id for item in self.outcomes) != (None, *self.request.candidates):
            raise ValueError('review outcomes do not cover the original conditions in order')


def assemble_review_result(
    resolved: ResolvedReviewRequest, outcomes: Iterable[ConditionOutcome]
) -> ReviewResult:
    return ReviewResult(
        resolved.request, (resolved.left.provenance, resolved.right.provenance), tuple(outcomes)
    )
