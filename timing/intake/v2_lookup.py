from dataclasses import dataclass

from timing.intake.lookup import StationProvenance
from timing.intake.receipt_store import ReceiptStore
from timing.intake.v2_checks import VerifiedV2Station, verify_station_v2
from timing.source.rounds import require_number


@dataclass(frozen=True)
class ReceivedV2Station:
    provenance: StationProvenance
    station: VerifiedV2Station
    replay_count: int


def get_received_station_v2(store: ReceiptStore, receipt_id: int) -> ReceivedV2Station:
    stored = store.fetch_receipt(require_number(receipt_id, 'intake receipt number'))
    if stored is None:
        raise KeyError(f'unknown intake receipt {receipt_id}')
    content, replay_count = stored
    verified = verify_station_v2(content)
    envelope = verified.envelope
    provenance = StationProvenance(
        receipt_id, envelope.station_id, envelope.issue_id, envelope.round_id, envelope.revision_id,
    )
    return ReceivedV2Station(provenance, verified, replay_count)
