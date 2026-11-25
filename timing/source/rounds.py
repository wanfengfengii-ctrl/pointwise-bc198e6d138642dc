from dataclasses import dataclass


@dataclass(frozen=True)
class RoundSpec:
    round_id: str
    anchors: tuple[str, str]


def require_identifier(value: object, field: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f'{field} must be a nonempty, trimmed string')
    return value


def require_anchor_pair(value: object) -> tuple[str, str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('exactly two public anchors are required')
    first = require_identifier(value[0], 'first public anchor')
    second = require_identifier(value[1], 'second public anchor')
    if first == second:
        raise ValueError('public anchors must be distinct')
    return first, second


def require_number(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f'{field} must be a positive integer')
    return value


def validate_round(spec: RoundSpec) -> RoundSpec:
    if not isinstance(spec, RoundSpec):
        raise ValueError('a RoundSpec is required')
    return RoundSpec(
        require_identifier(spec.round_id, 'round identity'),
        require_anchor_pair(spec.anchors),
    )
