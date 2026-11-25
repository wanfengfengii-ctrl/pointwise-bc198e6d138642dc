from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from timing.source.ledger import SourceLedger
from timing.source.observations import Observation, validate_observations
from timing.source.rounds import RoundSpec, require_identifier, require_number, validate_round
from timing.source.vouchers import Voucher, VoucherRoster, build_voucher_roster


@dataclass(frozen=True)
class Revision:
    revision_id: int
    station_id: str
    spec: RoundSpec
    roster: VoucherRoster
    observations: tuple[Observation, ...]
    parent_id: int | None


def register_round(ledger: SourceLedger, spec: RoundSpec, vouchers: Iterable[Voucher]) -> None:
    spec = validate_round(spec)
    roster = build_voucher_roster(vouchers)
    ledger.insert_round(
        spec.round_id,
        spec.anchors,
        tuple((entry.voucher_id, entry.label, entry.withdrawable) for entry in roster.entries),
    )


def _load_round(ledger: SourceLedger, round_id: str) -> tuple[RoundSpec, VoucherRoster]:
    stored = ledger.fetch_round(require_identifier(round_id, 'round identity'))
    if stored is None:
        raise KeyError(f'unknown round {round_id!r}')
    anchors, vouchers = stored
    return RoundSpec(round_id, anchors), VoucherRoster(tuple(Voucher(*row) for row in vouchers))


def save_revision(
    ledger: SourceLedger,
    round_id: str,
    observations: Iterable[Observation],
    parent_id: int | None = None,
) -> int:
    _, roster = _load_round(ledger, round_id)
    if parent_id is not None:
        parent = ledger.fetch_revision(require_number(parent_id, 'parent revision number'))
        if parent is None:
            raise KeyError(f'unknown parent revision {parent_id}')
        if parent[0] != round_id:
            raise ValueError('parent revision belongs to another round')
    rows = validate_observations(observations, roster)
    stored = (
        (row.start, row.end, str(row.upper_ms.numerator), str(row.upper_ms.denominator), row.voucher_id)
        for row in rows
    )
    return ledger.insert_revision(round_id, parent_id, stored)


def load_revision(ledger: SourceLedger, revision_id: int) -> Revision:
    stored = ledger.fetch_revision(require_number(revision_id, 'revision number'))
    if stored is None:
        raise KeyError(f'unknown revision {revision_id}')
    round_id, parent_id, rows = stored
    spec, roster = _load_round(ledger, round_id)
    observations = tuple(
        Observation(start, end, Fraction(int(numerator), int(denominator)), voucher)
        for start, end, numerator, denominator, voucher in rows
    )
    return Revision(revision_id, ledger.station_id, spec, roster, observations, parent_id)
