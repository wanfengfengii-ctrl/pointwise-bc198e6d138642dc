from dataclasses import dataclass

from timing.intake.checks import VerifiedStation, verify_station
from timing.intake.receipt_store import ReceiptStore
from timing.source.rounds import require_number


@dataclass(frozen=True)
class StationProvenance:
    receipt_id: int
    station_id: str
    issue_id: int
    round_id: str
    revision_id: int


@dataclass(frozen=True)
class ReceivedStation:
    provenance: StationProvenance
    station: VerifiedStation
    replay_count: int


def get_received_station(store: ReceiptStore, receipt_id: int) -> ReceivedStation:
    stored = store.fetch_receipt(require_number(receipt_id, 'intake receipt number'))
    if stored is None:
        raise KeyError(f'unknown intake receipt {receipt_id}')
    content, replay_count = stored
    verified = verify_station(content)
    envelope = verified.envelope
    provenance = StationProvenance(
        receipt_id, envelope.station_id, envelope.issue_id, envelope.round_id, envelope.revision_id,
    )
    return ReceivedStation(provenance, verified, replay_count)
