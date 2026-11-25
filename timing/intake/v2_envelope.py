import json
from dataclasses import dataclass

from timing.issue.tick import TickQualification, decode_tick_body, encode_tick_body
from timing.source.rounds import require_identifier, require_number


@dataclass(frozen=True)
class V2Envelope:
    station_id: str
    issue_id: int
    round_id: str
    revision_id: int
    body: dict
    version: int = 2


def encode_v2_envelope(envelope: V2Envelope) -> str:
    return json.dumps(
        {
            'version': envelope.version,
            'station_id': envelope.station_id,
            'issue_id': envelope.issue_id,
            'round_id': envelope.round_id,
            'revision_id': envelope.revision_id,
            'body': envelope.body,
        },
        ensure_ascii=True, allow_nan=False, separators=(',', ':'), sort_keys=True,
    )


def canonical_v2_envelope(envelope: V2Envelope) -> str:
    return encode_v2_envelope(envelope)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f'invalid JSON constant {value!r}')


def decode_v2_envelope(text: str) -> V2Envelope:
    if type(text) is not str:
        raise ValueError('station envelope must be JSON text')
    payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    fields = {'version', 'station_id', 'issue_id', 'round_id', 'revision_id', 'body'}
    if type(payload) is not dict or payload.keys() != fields:
        raise ValueError('invalid V2 envelope fields')
    if type(payload['version']) is not int or payload['version'] != 2:
        raise ValueError('unsupported station envelope version')
    if type(payload['body']) is not dict:
        raise ValueError('station envelope body must be an object')
    return V2Envelope(
        require_identifier(payload['station_id'], 'envelope station identity'),
        require_number(payload['issue_id'], 'envelope issue number'),
        require_identifier(payload['round_id'], 'envelope round identity'),
        require_number(payload['revision_id'], 'envelope revision number'),
        payload['body'],
    )


def build_v2_envelope(qualification: TickQualification) -> V2Envelope:
    body = encode_tick_body(qualification)
    return V2Envelope(
        qualification.station_id, qualification.issue_id,
        qualification.round_id, qualification.revision_id, body,
    )


def verify_v2_body(envelope: V2Envelope) -> TickQualification:
    qualification = decode_tick_body(envelope.body)
    outer = (envelope.station_id, envelope.issue_id, envelope.round_id, envelope.revision_id)
    inner = (
        qualification.station_id, qualification.issue_id,
        qualification.round_id, qualification.revision_id,
    )
    if outer != inner:
        raise ValueError('station body identity does not match the envelope')
    return qualification
