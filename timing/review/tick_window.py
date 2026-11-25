"""V2 tick-window signing: earliest jointly feasible lattice difference.

The center only uses the two centrally received V2 station documents.  Both
must belong to the same round, come from different stations, and register the
same ordered anchor pair.  A window is a finite closed rational interval; the
earliest common feasible value inside it is stored, or ``None`` when the two
stations share no feasible value there.  Empty settings are still signed.
"""

import json
from dataclasses import dataclass
from fractions import Fraction

from timing.archive.archive_store import ArchiveStore
from timing.intake.lookup import StationProvenance
from timing.intake.receipt_store import ReceiptStore
from timing.intake.v2_lookup import ReceivedV2Station, get_received_station_v2
from timing.issue.intervals import TimeInterval
from timing.issue.tick import TickQualification, decode_rational
from timing.source.observations import parse_rational_ms
from timing.source.rounds import require_identifier, require_number


@dataclass(frozen=True)
class TickWindowRequest:
    receipt_ids: tuple[int, int]
    lo_ms: Fraction
    hi_ms: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_ids, (list, tuple)) or len(self.receipt_ids) != 2:
            raise ValueError('exactly two ordered intake receipts are required')
        ids = tuple(require_number(value, 'intake receipt number') for value in self.receipt_ids)
        if ids[0] == ids[1]:
            raise ValueError('the two intake receipts must be distinct')
        lo = parse_rational_ms(self.lo_ms)
        hi = parse_rational_ms(self.hi_ms)
        if lo < 0 or hi < lo:
            raise ValueError('the window must be a finite closed interval with 0 <= lo <= hi')
        object.__setattr__(self, 'receipt_ids', ids)
        object.__setattr__(self, 'lo_ms', lo)
        object.__setattr__(self, 'hi_ms', hi)


@dataclass(frozen=True)
class TickWindowReport:
    report_id: int
    commit_receipt_id: int
    lo_ms: Fraction
    hi_ms: Fraction
    earliest_ms: Fraction | None
    sources: tuple[StationProvenance, StationProvenance]


def _load_pair(store: ReceiptStore, request: TickWindowRequest) -> tuple[ReceivedV2Station, ReceivedV2Station]:
    left = get_received_station_v2(store, request.receipt_ids[0])
    right = get_received_station_v2(store, request.receipt_ids[1])
    left_proof = left.provenance
    right_proof = right.provenance
    if left_proof.round_id != right_proof.round_id:
        raise ValueError('intake receipts belong to different rounds')
    if left_proof.station_id == right_proof.station_id:
        raise ValueError('intake receipts must represent two distinct stations')
    left_anchors = left.station.qualification.anchors
    if left_anchors != right.station.qualification.anchors:
        raise ValueError('the two V2 documents must register the same ordered anchor pair')
    return left, right


def _validate_v2(left: ReceivedV2Station, right: ReceivedV2Station) -> None:
    for received in (left, right):
        if received.station.envelope.version != 2:
            raise ValueError('tick window signing requires V2 station documents')


def _candidate_values(qualification: TickQualification,
                      window: TimeInterval) -> list[Fraction]:
    """All points where the station's feasibility can change inside the window.

    Station continuous bounds are not used to shrink the enumeration: every
    candidate is later checked with ``contains``, and clipping here would drop
    boundary beats that sit outside the station bound yet are needed to span
    the requested window for later candidates.  An empty phase tuple means
    every fractional part is feasible, contributing only the window's origin.
    """
    lower, upper = window.lower, window.upper
    tick = qualification.tick_ms
    candidates: set[Fraction] = {lower}
    if not qualification.phases:
        return sorted(candidates)
    k_min = floor_div(lower, tick)
    k_max = floor_div(upper, tick)
    for phase in qualification.phases:
        for beat in range(k_min, k_max + 1):
            low = tick * (beat + phase.lower)
            high = tick * (beat + phase.upper)
            if lower <= low <= upper:
                candidates.add(low)
            if lower <= high <= upper:
                candidates.add(high)
    return sorted(candidates)


def floor_div(value: Fraction, tick: Fraction) -> int:
    return (value / tick).__floor__()


def _earliest_common(left: TickQualification, right: TickQualification,
                     window: TimeInterval) -> Fraction | None:
    if not left.feasible or not right.feasible:
        return None
    candidates = sorted(set(_candidate_values(left, window)) | set(_candidate_values(right, window)))
    for candidate in candidates:
        if left.contains(candidate) and right.contains(candidate):
            return candidate
    return None


def sign_tick_window(archive: ArchiveStore, receipt_ids, lo_ms, hi_ms) -> TickWindowReport:
    request = TickWindowRequest(tuple(receipt_ids), lo_ms, hi_ms)
    db = archive.connection
    db.execute('BEGIN IMMEDIATE')
    with db:
        store = ReceiptStore(db)
        left, right = _load_pair(store, request)
        _validate_v2(left, right)
        window = TimeInterval(request.lo_ms, request.hi_ms)
        earliest = _earliest_common(
            left.station.qualification, right.station.qualification, window
        )
        sources = (left.provenance, right.provenance)
        report_id, commit_receipt_id = archive.insert_tick_window(
            encode_tick_window_report(request, earliest, sources), request.receipt_ids
        )
    return TickWindowReport(
        report_id, commit_receipt_id, request.lo_ms, request.hi_ms, earliest, sources
    )


def encode_tick_window_report(
    request: TickWindowRequest, earliest: Fraction | None,
    sources: tuple[StationProvenance, StationProvenance],
) -> str:
    data = {
        'request': {
            'receipt_ids': list(request.receipt_ids),
            'lo_ms': [request.lo_ms.numerator, request.lo_ms.denominator],
            'hi_ms': [request.hi_ms.numerator, request.hi_ms.denominator],
        },
        'sources': [
            {
                'receipt_id': source.receipt_id,
                'station_id': source.station_id,
                'issue_id': source.issue_id,
                'round_id': source.round_id,
                'revision_id': source.revision_id,
            }
            for source in sources
        ],
        'earliest_ms': None if earliest is None
        else [earliest.numerator, earliest.denominator],
    }
    return json.dumps(data, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':'), sort_keys=True)


def decode_tick_window_report(report_id: int, content: str) -> TickWindowReport:
    number = require_number(report_id, 'report number')
    data = json.loads(content)
    if data.keys() != {'request', 'sources', 'earliest_ms'}:
        raise ValueError('invalid archived tick window report fields')
    request_data = data['request']
    if request_data.keys() != {'receipt_ids', 'lo_ms', 'hi_ms'}:
        raise ValueError('invalid archived tick window request fields')
    receipt_ids = tuple(
        require_number(value, 'archived intake number') for value in request_data['receipt_ids']
    )
    if len(receipt_ids) != 2 or receipt_ids[0] == receipt_ids[1]:
        raise ValueError('archived tick window request must hold two distinct receipts')
    lo = decode_rational(request_data['lo_ms'])
    hi = decode_rational(request_data['hi_ms'])
    if lo < 0 or hi < lo:
        raise ValueError('archived tick window is not a finite closed nonnegative window')
    sources = tuple(_decode_source(item) for item in data['sources'])
    if len(sources) != 2 or tuple(item.receipt_id for item in sources) != receipt_ids:
        raise ValueError('archived tick window provenance does not match its request')
    earliest = None if data['earliest_ms'] is None else decode_rational(data['earliest_ms'])
    return TickWindowReport(number, 0, lo, hi, earliest, sources)


def _decode_source(item: object) -> StationProvenance:
    if type(item) is not dict or item.keys() != {
        'receipt_id', 'station_id', 'issue_id', 'round_id', 'revision_id'
    }:
        raise ValueError('invalid archived tick window provenance fields')
    return StationProvenance(
        require_number(item['receipt_id'], 'archived intake number'),
        require_identifier(item['station_id'], 'archived station identity'),
        require_number(item['issue_id'], 'archived issue number'),
        require_identifier(item['round_id'], 'archived round identity'),
        require_number(item['revision_id'], 'archived revision number'),
    )
