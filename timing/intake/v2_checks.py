from dataclasses import dataclass

from timing.intake.v2_envelope import V2Envelope, decode_v2_envelope, verify_v2_body
from timing.issue.tick import TickQualification


@dataclass(frozen=True)
class VerifiedV2Station:
    envelope: V2Envelope
    qualification: TickQualification


def verify_station_v2(text: str) -> VerifiedV2Station:
    envelope = decode_v2_envelope(text)
    qualification = verify_v2_body(envelope)
    return VerifiedV2Station(envelope, qualification)
