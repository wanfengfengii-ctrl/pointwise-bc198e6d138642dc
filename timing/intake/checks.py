from dataclasses import dataclass

from timing.intake.envelope import V1Envelope, canonical_envelope, decode_envelope
from timing.issue.evidence import StationEvidence, decode_station_body


@dataclass(frozen=True)
class VerifiedStation:
    envelope: V1Envelope
    evidence: StationEvidence


def verify_station(value: V1Envelope | str) -> VerifiedStation:
    if isinstance(value, V1Envelope):
        try:
            value = canonical_envelope(value)
        except TypeError as exc:
            raise ValueError('station envelope is not JSON encodable') from exc
    envelope = decode_envelope(value)
    evidence = decode_station_body(envelope.body)
    outer = (envelope.station_id, envelope.issue_id, envelope.round_id, envelope.revision_id)
    inner = (evidence.station_id, evidence.issue_id, evidence.round_id, evidence.revision_id)
    if outer != inner:
        raise ValueError('station body identity does not match the envelope')
    return VerifiedStation(envelope, evidence)
