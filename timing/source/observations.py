from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from timing.source.rounds import require_identifier
from timing.source.vouchers import VoucherRoster


@dataclass(frozen=True)
class Observation:
    start: str
    end: str
    upper_ms: Fraction | int | str
    voucher_id: str


def parse_rational_ms(value: object) -> Fraction:
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    if type(value) is str:
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f'invalid rational millisecond bound {value!r}') from exc
    raise ValueError('an exact rational millisecond bound is required')


def validate_observations(
    observations: Iterable[Observation], roster: VoucherRoster
) -> tuple[Observation, ...]:
    result = []
    for row in observations:
        if not isinstance(row, Observation):
            raise ValueError('observation rows must be Observation objects')
        start = require_identifier(row.start, 'start event')
        end = require_identifier(row.end, 'end event')
        voucher = roster[require_identifier(row.voucher_id, 'observation voucher')]
        result.append(Observation(start, end, parse_rational_ms(row.upper_ms), voucher.voucher_id))
    return tuple(result)
