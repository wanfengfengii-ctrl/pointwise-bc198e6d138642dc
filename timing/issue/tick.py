"""Exact tick-qualified timing projections for V2 station documents.

Private events and the first anchor U take times on the station lattice
``tick_ms * Z`` (negative beats included).  The second anchor V keeps a
continuous time ``d`` measured from U.  For a fixed ``d`` every observation
``t(end) - t(start) <= upper`` must hold at once, including components that
never touch the public anchors.

Writing lattice vertex ``x`` as ``t(x) = tick * k_x`` with ``k_x`` integer,
edges between lattice vertices become integer difference constraints with
floored right-hand sides.  Edges incident on V either bound ``d`` continuously
or restrict the fractional part ``f`` of ``d / tick``.  Feasible fractional
parts are closed rational slices of the unit circle.

A phase slice is stored as endpoints in ``[0, 1)``.  An ordinary slice has
``lower <= upper``; a wrapping slice through the origin has ``lower > upper``
and means ``[lower, 1) union {0} union [0, upper]``.  There is no sentinel
value: an isolated beat is a slice whose two endpoints are equal, while an
empty tuple of phases means "no fractional-part restriction" (every phase is
feasible).  A conflicting qualification stores ``None`` instead.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor

from timing.issue.intervals import TimeInterval
from timing.source.observations import parse_rational_ms
from timing.source.rounds import require_anchor_pair, require_identifier, require_number

ZERO = Fraction(0)
ONE = Fraction(1)


def parse_tick_ms(value: object) -> Fraction:
    tick = parse_rational_ms(value)
    if tick <= 0:
        raise ValueError('tick_ms must be a positive rational millisecond value')
    return tick


def decode_rational(value: object) -> Fraction:
    if type(value) is not list or len(value) != 2:
        raise ValueError('a rational value must be a numerator and denominator pair')
    numerator, denominator = value
    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        raise ValueError('rational values require an integer numerator and a positive denominator')
    result = Fraction(numerator, denominator)
    if (result.numerator, result.denominator) != (numerator, denominator):
        raise ValueError('rational values must be reduced fractions')
    return result


def decode_tick_ms(value: object) -> Fraction:
    tick = decode_rational(value)
    if tick <= 0:
        raise ValueError('tick_ms must be a positive rational millisecond value')
    return tick


@dataclass(frozen=True)
class PhaseInterval:
    """A closed slice of the unit circle of fractional parts in [0, 1).

    An ordinary slice has ``lower <= upper`` and ``wraps is False``.  A
    wrapping slice has ``lower > upper`` and means
    ``[lower, 1) union {0} union [0, upper]`` when ``includes_origin`` is set,
    otherwise it is only ``[lower, 1)`` (the origin point is excluded).
    """

    lower: Fraction
    upper: Fraction
    includes_origin: bool = True

    def __post_init__(self) -> None:
        for field in ('lower', 'upper'):
            value = getattr(self, field)
            if type(value) is int:
                object.__setattr__(self, field, Fraction(value))
            elif not isinstance(value, Fraction):
                raise ValueError('phase endpoints must be exact rational numbers')
        if not (ZERO <= self.lower < ONE and ZERO <= self.upper < ONE):
            raise ValueError('phase endpoints must lie in [0, 1)')
        if type(self.includes_origin) is not bool:
            raise ValueError('includes_origin must be a boolean')
        if not self.wraps and self.includes_origin is False and self.lower != self.upper:
            raise ValueError('only wrapping sections may exclude the origin')

    @property
    def wraps(self) -> bool:
        return self.lower > self.upper

    @property
    def singleton(self) -> bool:
        return self.lower == self.upper and not self.wraps

    @classmethod
    def from_payload(cls, payload: object) -> 'PhaseInterval':
        if type(payload) is not list or len(payload) not in (2, 3):
            raise ValueError('a phase interval must be endpoint pairs and an optional origin flag')
        lower = decode_rational(payload[0])
        upper = decode_rational(payload[1])
        includes_origin = True if len(payload) == 2 else bool(payload[2])
        if len(payload) == 3 and type(payload[2]) is not bool:
            raise ValueError('the phase origin flag must be a boolean')
        return cls(lower, upper, includes_origin)

    def to_payload(self) -> list:
        endpoints = [
            [self.lower.numerator, self.lower.denominator],
            [self.upper.numerator, self.upper.denominator],
        ]
        if self.wraps and not self.includes_origin:
            endpoints.append(False)
        return endpoints


def whole_circle_sections() -> tuple[PhaseInterval, ...]:
    # An empty phase tuple means every fractional part is feasible.
    return ()


@dataclass(frozen=True)
class TickQualification:
    station_id: str
    round_id: str
    revision_id: int
    issue_id: int | None
    anchors: tuple[str, str]
    tick_ms: Fraction
    feasible: bool
    bounds: TimeInterval | None
    phases: tuple[PhaseInterval, ...] | None

    def contains(self, value: Fraction) -> bool:
        """Whether the continuous public difference ``value`` is station-feasible."""
        if not self.feasible:
            return False
        assert self.bounds is not None and self.phases is not None
        if self.bounds.lower is not None and value < self.bounds.lower:
            return False
        if self.bounds.upper is not None and value > self.bounds.upper:
            return False
        phase = (value / self.tick_ms) % 1
        if not self.phases:
            return True
        for section in self.phases:
            if section.wraps:
                if phase >= section.lower:
                    return True
                if section.includes_origin and phase <= section.upper:
                    return True
            elif section.lower <= phase <= section.upper:
                return True
        return False


def build_tick_qualification(
    revision, tick_ms: Fraction | int | str, issue_id: int | None = None
) -> TickQualification:
    anchors = require_anchor_pair(revision.spec.anchors)
    tick = parse_tick_ms(tick_ms)
    if issue_id is not None:
        require_number(issue_id, 'issue number')
    first_anchor, second_anchor = anchors

    lattice: set[str] = {first_anchor}
    v_incoming: list[tuple[str, Fraction]] = []  # V -> x, weight in tick units
    v_outgoing: list[tuple[str, Fraction]] = []  # y -> V, weight in tick units
    anchor_upper: list[Fraction] = []  # direct U -> V bounds on d / tick
    anchor_lower: list[Fraction] = []  # direct V -> U bounds on d / tick
    lattice_edges: list[tuple[str, str, Fraction]] = []
    for row in revision.observations:
        weight = row.upper_ms / tick
        if row.start == second_anchor:
            if row.end == first_anchor:
                # V -> U: t(U) - t(V) <= w  =>  d >= -w (tick units).
                anchor_lower.append(-weight)
                continue
            lattice.add(row.end)
            v_incoming.append((row.end, weight))
        elif row.end == second_anchor:
            if row.start == first_anchor:
                # U -> V: d <= w (tick units).
                anchor_upper.append(weight)
                continue
            lattice.add(row.start)
            v_outgoing.append((row.start, weight))
        else:
            lattice.add(row.start)
            lattice.add(row.end)
            lattice_edges.append((row.start, row.end, weight))
    lattice_tuple = tuple(sorted(lattice))
    index = {name: position for position, name in enumerate(lattice_tuple)}
    size = len(lattice_tuple)

    # Integer shortest paths on the floored lattice difference graph.
    dist: list[list[Fraction | None]] = [
        [ZERO if column == row else None for column in range(size)] for row in range(size)
    ]
    for start_name, end_name, weight in lattice_edges:
        start = index[start_name]
        end = index[end_name]
        floored = Fraction(floor(weight))
        current = dist[start][end]
        if current is None or floored < current:
            dist[start][end] = floored
    for middle in range(size):
        row_middle = dist[middle]
        for start in range(size):
            prefix = dist[start][middle]
            if prefix is None:
                continue
            row_start = dist[start]
            for end in range(size):
                suffix = row_middle[end]
                if suffix is None:
                    continue
                proposed = prefix + suffix
                if row_start[end] is None or proposed < row_start[end]:
                    row_start[end] = proposed

    if any(dist[vertex][vertex] < 0 for vertex in range(size)):
        return _conflict(revision, issue_id, anchors, tick)

    zero = index[first_anchor]
    lower = tick * max(anchor_lower) if anchor_lower else None
    upper = tick * min(anchor_upper) if anchor_upper else None

    # V -> x of weight wv (tick units) gives k_x - f <= wv, so routing the
    # integer path x -> U (k_U - k_x <= P) yields f >= -P - wv (lower bound).
    # y -> V of weight wu gives f - k_y <= wu; routing U -> y (k_y <= P)
    # yields f <= P + wu (upper bound).
    for event, wv in v_incoming:
        path = dist[index[event]][zero]
        if path is not None:
            candidate = tick * (-path - wv)
            if lower is None or candidate > lower:
                lower = candidate
    for event, wu in v_outgoing:
        path = dist[zero][index[event]]
        if path is not None:
            candidate = tick * (path + wu)
            if upper is None or candidate < upper:
                upper = candidate

    # A V -> x edge of weight wv bounds k_x <= f + wv; a y -> V edge of
    # weight wu bounds k_y >= f - wu.  Joined by the integer path x -> y of
    # length P (k_y - k_x <= P), feasibility of integer k requires
    #   ceil(f - wu) - floor(f + wv) <= P.
    restrictions = [
        (wv, wu, dist[index[x]][index[y]])
        for x, wv in v_incoming
        for y, wu in v_outgoing
        if dist[index[x]][index[y]] is not None
    ]
    phases = build_phase_sections(restrictions)
    if phases is None:
        return _conflict(revision, issue_id, anchors, tick)
    if lower is not None and upper is not None and lower > upper:
        return _conflict(revision, issue_id, anchors, tick)
    return TickQualification(
        revision.station_id, revision.spec.round_id, revision.revision_id, issue_id,
        anchors, tick, True, TimeInterval(lower, upper), phases,
    )


def _conflict(revision, issue_id, anchors, tick) -> TickQualification:
    return TickQualification(
        revision.station_id, revision.spec.round_id, revision.revision_id, issue_id,
        anchors, tick, False, None, None,
    )


def build_phase_sections(
    restrictions: list[tuple[Fraction, Fraction, Fraction]]
) -> tuple[PhaseInterval, ...] | None:
    """Return feasible circle sections, an empty tuple for the whole circle,
    or ``None`` when the restrictions leave no feasible fractional part."""
    if not restrictions:
        return whole_circle_sections()
    sections: list[PhaseInterval] | None = None
    for restriction in restrictions:
        extra = _single_restriction_sections(restriction)
        if extra is None:
            return None
        if sections is None:
            sections = list(extra)
            continue
        if not extra:
            # Whole circle intersects as the identity.
            continue
        sections = intersect_phase_sections(sections, extra)
        if not sections:
            return None
    return tuple(sections) if sections is not None else whole_circle_sections()


def _single_restriction_sections(
    restriction: tuple[Fraction, Fraction, Fraction]
) -> list[PhaseInterval] | None:
    # Restriction after eliminating the integer path x -> y of length P:
    #   ceil(f - wu) - floor(f + wv) <= P.
    wv, wu, path = restriction
    # floor(f + wv) jumps upward at (-wv) mod 1 and ceil(f - wu) jumps upward
    # at wu mod 1.  The left-hand side is constant on each half-open slice
    # [cut_i, cut_{i+1}) of the partition of [0, 1).  A slice is included via
    # an interior probe; feasible cuts are added independently so isolated
    # feasible beats survive.
    cuts = sorted({ZERO, (-wv) % 1, wu % 1})

    def holds(fraction: Fraction) -> bool:
        return ceil(fraction - wu) - floor(fraction + wv) <= path

    pieces: list[tuple[Fraction, Fraction]] = []
    for position, left in enumerate(cuts):
        right = cuts[position + 1] if position + 1 < len(cuts) else ONE
        if holds(left):
            pieces.append((left, left))
        if right > left and holds((left + right) / 2):
            pieces.append((left, right))
    if not pieces:
        return None
    return _pieces_to_sections(pieces)


def _explode(section: PhaseInterval) -> list[tuple[Fraction, Fraction]]:
    """Expand a circle section into half-open pieces on the real line."""
    if section.wraps:
        pieces = [(section.lower, ONE)]
        if section.includes_origin:
            pieces.append((ZERO, section.upper))
        return pieces
    if section.singleton:
        return [(section.lower, section.lower)]
    return [(section.lower, section.upper)]


def intersect_phase_sections(
    left: list[PhaseInterval], right: list[PhaseInterval]
) -> list[PhaseInterval]:
    left_pieces: list[tuple[Fraction, Fraction]] = []
    right_pieces: list[tuple[Fraction, Fraction]] = []
    for section in left:
        left_pieces.extend(_explode(section))
    for section in right:
        right_pieces.extend(_explode(section))
    pieces: list[tuple[Fraction, Fraction]] = []
    for first_low, first_high in left_pieces:
        first_is_point = first_low == first_high
        for second_low, second_high in right_pieces:
            second_is_point = second_low == second_high
            if first_is_point or second_is_point:
                point = first_low if first_is_point else second_low
                if _piece_contains(first_low, first_high, point) and _piece_contains(
                    second_low, second_high, point
                ):
                    pieces.append((point, point))
                continue
            low = max(first_low, second_low)
            high = min(first_high, second_high)
            if low < high:
                pieces.append((low, high))
            elif low == high and low < ONE:
                pieces.append((low, low))
    return _pieces_to_sections(pieces)


def _piece_contains(low: Fraction, high: Fraction, point: Fraction) -> bool:
    if low == high:
        return point == low
    return low <= point < high


def _pieces_to_sections(pieces: list[tuple[Fraction, Fraction]]) -> list[PhaseInterval]:
    """Turn half-open real-line pieces into normalized circle sections.

    Positive-length pieces merge as ordinary intervals; isolated points stay
    separate unless covered by a positive-length piece.  A piece reaching 1
    wraps through the origin and joins any piece starting at 0.
    """
    points = {low for low, high in pieces if low == high}
    spans = sorted(([low, high] for low, high in pieces if low < high),
                   key=lambda item: (item[0], item[1]))
    merged: list[list[Fraction]] = []
    for low, high in spans:
        if merged and merged[-1][1] > low:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([low, high])

    covered = {
        point
        for low, high in merged
        for point in points
        if low <= point < high
    }
    isolated = sorted(points - covered)

    if not merged:
        return [PhaseInterval(point, point) for point in isolated]
    if len(merged) == 1 and merged[0] == [ZERO, ONE]:
        # A span covering [0, 1) already contains every phase (the origin
        # point included), so this is the whole circle regardless of isolated
        # points collected alongside it.
        return []

    origin_span = next((piece for piece in merged if piece[0] == 0), None)
    tail_span = next((piece for piece in merged if piece[1] == 1), None)
    origin_feasible = origin_span is not None or ZERO in isolated
    sections: list[PhaseInterval] = []
    for low, high in merged:
        if high == 1:
            continue
        sections.append(PhaseInterval(low, high))
    for point in isolated:
        if point == 0 and tail_span is not None:
            continue
        sections.append(PhaseInterval(point, point))
    if tail_span is not None:
        if origin_feasible:
            upper = origin_span[1] if origin_span is not None else ZERO
            if tail_span[0] <= upper:
                # The tail wraps into the origin section and the two meet,
                # covering the whole circle.
                return []
            sections.append(PhaseInterval(tail_span[0], upper, True))
        else:
            # No feasible origin: represent [low, 1) as a wrapping section
            # that explicitly excludes the origin point.
            sections.append(PhaseInterval(tail_span[0], ZERO, False))
    return sections


def encode_tick_body(qualification: TickQualification) -> dict:
    require_number(qualification.issue_id, 'body issue number')
    return {
        'station_id': require_identifier(qualification.station_id, 'body station identity'),
        'issue_id': qualification.issue_id,
        'round_id': require_identifier(qualification.round_id, 'body round identity'),
        'revision_id': require_number(qualification.revision_id, 'body revision number'),
        'anchors': list(require_anchor_pair(qualification.anchors)),
        'tick_ms': [qualification.tick_ms.numerator, qualification.tick_ms.denominator],
        'status': 'feasible' if qualification.feasible else 'conflict',
        'bounds': None if qualification.bounds is None else qualification.bounds.to_payload(),
        'phases': None if qualification.phases is None
        else [section.to_payload() for section in qualification.phases],
    }


def decode_tick_body(body: object) -> TickQualification:
    fields = {'station_id', 'issue_id', 'round_id', 'revision_id',
              'anchors', 'tick_ms', 'status', 'bounds', 'phases'}
    if type(body) is not dict or body.keys() != fields:
        raise ValueError('invalid V2 station body fields')
    station = require_identifier(body['station_id'], 'body station identity')
    round_id = require_identifier(body['round_id'], 'body round identity')
    revision = require_number(body['revision_id'], 'body revision number')
    issue = require_number(body['issue_id'], 'body issue number')
    anchors = require_anchor_pair(body['anchors'])
    tick = decode_tick_ms(body['tick_ms'])
    status = body['status']
    if status not in ('feasible', 'conflict'):
        raise ValueError('invalid V2 qualification status')
    if status == 'conflict':
        if body['bounds'] is not None or body['phases'] is not None:
            raise ValueError('a conflicting V2 qualification must carry empty projections')
        return TickQualification(station, round_id, revision, issue, anchors, tick, False, None, None)
    if type(body['phases']) is not list:
        raise ValueError('a feasible V2 qualification requires a phases array')
    phases = tuple(PhaseInterval.from_payload(item) for item in body['phases'])
    return TickQualification(
        station, round_id, revision, issue, anchors, tick, True,
        TimeInterval.from_payload(body['bounds']), phases,
    )
