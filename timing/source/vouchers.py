from collections.abc import Iterable
from dataclasses import dataclass

from timing.source.rounds import require_identifier


@dataclass(frozen=True)
class Voucher:
    voucher_id: str
    label: str | None = None
    withdrawable: bool = True


@dataclass(frozen=True)
class VoucherRoster:
    entries: tuple[Voucher, ...]

    def __getitem__(self, voucher_id: str) -> Voucher:
        for voucher in self.entries:
            if voucher.voucher_id == voucher_id:
                return voucher
        raise ValueError(f'unknown voucher {voucher_id!r}')


def build_voucher_roster(vouchers: Iterable[Voucher]) -> VoucherRoster:
    registered = {}
    for voucher in vouchers:
        if not isinstance(voucher, Voucher):
            raise ValueError('roster entries must be Voucher objects')
        key = require_identifier(voucher.voucher_id, 'voucher identity')
        if key in registered:
            raise ValueError(f'duplicate voucher {key!r}')
        label = key if voucher.label is None else require_identifier(voucher.label, 'voucher label')
        if type(voucher.withdrawable) is not bool:
            raise ValueError('withdrawable must be a boolean')
        registered[key] = Voucher(key, label, voucher.withdrawable)
    return VoucherRoster(tuple(registered.values()))


def resolve_candidate_vouchers(
    roster: VoucherRoster, candidates: Iterable[str] | None = None
) -> tuple[str, ...]:
    if candidates is None:
        return tuple(voucher.voucher_id for voucher in roster.entries if voucher.withdrawable)
    if isinstance(candidates, (str, bytes)):
        raise ValueError('candidates must be a collection of voucher identities')
    selected = {}
    for candidate in candidates:
        key = require_identifier(candidate, 'candidate voucher')
        if not roster[key].withdrawable:
            raise ValueError(f'voucher {key!r} is retained for this round')
        selected[key] = None
    return tuple(selected)
