from dataclasses import dataclass
from fractions import Fraction


def _decode_endpoint(value: object) -> Fraction | None:
    if value is None:
        return None
    if type(value) is not list or len(value) != 2:
        raise ValueError('a finite endpoint must be a numerator and denominator pair')
    numerator, denominator = value
    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        raise ValueError('endpoint requires an integer numerator and a positive integer denominator')
    endpoint = Fraction(numerator, denominator)
    if (endpoint.numerator, endpoint.denominator) != (numerator, denominator):
        raise ValueError('endpoint fraction must be reduced')
    return endpoint


def _encode_endpoint(value: Fraction | None) -> list[int] | None:
    if value is None:
        return None
    return [value.numerator, value.denominator]


@dataclass(frozen=True)
class TimeInterval:
    lower: Fraction | None
    upper: Fraction | None

    def __post_init__(self) -> None:
        for field in ('lower', 'upper'):
            value = getattr(self, field)
            if type(value) is int:
                object.__setattr__(self, field, Fraction(value))
            elif value is not None and not isinstance(value, Fraction):
                raise ValueError('finite endpoints must be exact rational numbers')
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError('interval lower endpoint exceeds its upper endpoint')

    @classmethod
    def from_payload(cls, payload: object) -> 'TimeInterval':
        if type(payload) is not dict or payload.keys() != {'lower', 'upper'}:
            raise ValueError('interval must contain lower and upper endpoints')
        return cls(_decode_endpoint(payload['lower']), _decode_endpoint(payload['upper']))

    def to_payload(self) -> dict:
        return {'lower': _encode_endpoint(self.lower), 'upper': _encode_endpoint(self.upper)}

    def reversed(self) -> 'TimeInterval':
        lower = None if self.upper is None else -self.upper
        upper = None if self.lower is None else -self.lower
        return TimeInterval(lower, upper)
