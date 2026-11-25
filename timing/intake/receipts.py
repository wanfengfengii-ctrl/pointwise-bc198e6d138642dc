from dataclasses import dataclass

from timing.intake.checks import verify_station
from timing.intake.envelope import V1Envelope, canonical_envelope
from timing.intake.receipt_store import ReceiptStore
from timing.intake.v2_checks import verify_station_v2
from timing.intake.v2_envelope import canonical_v2_envelope


@dataclass(frozen=True)
class Receipt:
    receipt_id: int
    station_id: str
    issue_id: int
    replay_count: int

    @property
    def replayed(self) -> bool:
        return self.replay_count > 0


def accept_station(store: ReceiptStore, incoming: V1Envelope | str) -> Receipt:
    verified = verify_station(incoming)
    envelope = verified.envelope
    receipt_id, replay_count = store.record_delivery(
        envelope.station_id, envelope.issue_id, canonical_envelope(envelope)
    )
    return Receipt(receipt_id, envelope.station_id, envelope.issue_id, replay_count)


def accept_station_v2(store: ReceiptStore, text: str) -> Receipt:
    verified = verify_station_v2(text)
    envelope = verified.envelope
    receipt_id, replay_count = store.record_delivery(
        envelope.station_id, envelope.issue_id, canonical_v2_envelope(envelope)
    )
    return Receipt(receipt_id, envelope.station_id, envelope.issue_id, replay_count)
