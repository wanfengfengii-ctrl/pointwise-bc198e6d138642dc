import json
from dataclasses import dataclass

from timing.source.rounds import require_identifier, require_number


@dataclass(frozen=True)
class V1Envelope:
    station_id: str
    issue_id: int
    round_id: str
    revision_id: int
    body: dict
    version: int = 1


def encode_envelope(envelope: V1Envelope) -> str:
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


def canonical_envelope(envelope: V1Envelope) -> str:
    return encode_envelope(envelope)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f'invalid JSON constant {value!r}')


def decode_envelope(text: str) -> V1Envelope:
    if type(text) is not str:
        raise ValueError('station envelope must be JSON text')
    payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    fields = {'version', 'station_id', 'issue_id', 'round_id', 'revision_id', 'body'}
    if type(payload) is not dict or payload.keys() != fields:
        raise ValueError('invalid V1 envelope fields')
    if type(payload['version']) is not int or payload['version'] != 1:
        raise ValueError('unsupported station envelope version')
    if type(payload['body']) is not dict:
        raise ValueError('station envelope body must be an object')
    return V1Envelope(
        require_identifier(payload['station_id'], 'envelope station identity'),
        require_number(payload['issue_id'], 'envelope issue number'),
        require_identifier(payload['round_id'], 'envelope round identity'),
        require_number(payload['revision_id'], 'envelope revision number'),
        payload['body'],
    )
