from dataclasses import dataclass

from timing.intake.lookup import ReceivedStation, get_received_station
from timing.intake.receipt_store import ReceiptStore
from timing.source.rounds import require_anchor_pair, require_identifier, require_number


@dataclass(frozen=True)
class ReviewRequest:
    receipt_ids: tuple[int, int]
    anchors: tuple[str, str]
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_ids, (list, tuple)) or len(self.receipt_ids) != 2:
            raise ValueError('exactly two ordered intake receipts are required')
        ids = tuple(require_number(value, 'intake receipt number') for value in self.receipt_ids)
        if ids[0] == ids[1]:
            raise ValueError('the two intake receipts must be distinct')
        if not isinstance(self.candidates, (list, tuple)):
            raise ValueError('candidates must be an ordered list or tuple')
        candidates = tuple(require_identifier(value, 'request candidate') for value in self.candidates)
        object.__setattr__(self, 'receipt_ids', ids)
        object.__setattr__(self, 'anchors', require_anchor_pair(self.anchors))
        object.__setattr__(self, 'candidates', candidates)


@dataclass(frozen=True)
class ResolvedReviewRequest:
    request: ReviewRequest
    left: ReceivedStation
    right: ReceivedStation


def resolve_review_request(store: ReceiptStore, request: ReviewRequest) -> ResolvedReviewRequest:
    if not isinstance(request, ReviewRequest):
        raise ValueError('a ReviewRequest is required')
    left = get_received_station(store, request.receipt_ids[0])
    right = get_received_station(store, request.receipt_ids[1])
    if left.provenance.round_id != right.provenance.round_id:
        raise ValueError('intake receipts belong to different rounds')
    if left.provenance.station_id == right.provenance.station_id:
        raise ValueError('intake receipts must represent two distinct stations')
    for item in (left, right):
        evidence = item.station.evidence
        if request.anchors not in (evidence.anchors, evidence.anchors[::-1]):
            raise ValueError('requested public anchors do not match both station documents')
        for candidate in request.candidates:
            if candidate not in evidence.candidates:
                raise ValueError(f'candidate {candidate!r} is unknown or not covered by both documents')
    return ResolvedReviewRequest(request, left, right)
