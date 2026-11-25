from dataclasses import dataclass

from timing.issue.bounds import build_constraint_graph, project_anchor_pair
from timing.issue.intervals import TimeInterval
from timing.issue.qualification import is_feasible
from timing.source.revisions import Revision
from timing.source.rounds import require_anchor_pair, require_identifier, require_number
from timing.source.vouchers import resolve_candidate_vouchers


@dataclass(frozen=True)
class ConditionEvidence:
    voucher_id: str | None
    interval: TimeInterval | None

    @property
    def status(self) -> str:
        return 'conflict' if self.interval is None else 'feasible'


@dataclass(frozen=True)
class StationEvidence:
    station_id: str
    round_id: str
    revision_id: int
    anchors: tuple[str, str]
    candidates: tuple[str, ...]
    conditions: tuple[ConditionEvidence, ...]
    issue_id: int | None = None


def build_station_evidence(
    revision: Revision, candidates: tuple[str, ...] | None = None
) -> StationEvidence:
    selected = resolve_candidate_vouchers(revision.roster, candidates)
    anchors = revision.spec.anchors
    conditions = []
    for voucher in (None, *selected):
        active = (row for row in revision.observations if row.voucher_id != voucher)
        graph = build_constraint_graph(active, anchors)
        interval = project_anchor_pair(graph, anchors) if is_feasible(graph) else None
        conditions.append(ConditionEvidence(voucher, interval))
    return StationEvidence(
        revision.station_id, revision.spec.round_id, revision.revision_id,
        anchors, selected, tuple(conditions),
    )


def encode_station_body(evidence: StationEvidence) -> dict:
    return {
        'station_id': evidence.station_id,
        'issue_id': require_number(evidence.issue_id, 'body issue number'),
        'round_id': evidence.round_id,
        'revision_id': evidence.revision_id,
        'anchors': list(evidence.anchors),
        'candidates': list(evidence.candidates),
        'conditions': [
            {
                'voucher_id': condition.voucher_id,
                'status': condition.status,
                'interval': None if condition.interval is None else condition.interval.to_payload(),
            }
            for condition in evidence.conditions
        ],
    }


def _decode_condition(payload: object, voucher_id: str | None) -> ConditionEvidence:
    if type(payload) is not dict or payload.keys() != {'voucher_id', 'status', 'interval'}:
        raise ValueError('invalid station condition fields')
    if payload['voucher_id'] != voucher_id:
        raise ValueError('station condition identity does not match declared coverage')
    if payload['status'] == 'conflict' and payload['interval'] is None:
        return ConditionEvidence(voucher_id, None)
    if payload['status'] == 'feasible':
        return ConditionEvidence(voucher_id, TimeInterval.from_payload(payload['interval']))
    raise ValueError('station condition status does not match its interval')


def decode_station_body(body: object) -> StationEvidence:
    fields = {'station_id', 'issue_id', 'round_id', 'revision_id', 'anchors', 'candidates', 'conditions'}
    if type(body) is not dict or body.keys() != fields:
        raise ValueError('invalid station body fields')
    station = require_identifier(body['station_id'], 'body station identity')
    round_id = require_identifier(body['round_id'], 'body round identity')
    revision = require_number(body['revision_id'], 'body revision number')
    issue = require_number(body['issue_id'], 'body issue number')
    anchors = require_anchor_pair(body['anchors'])
    if type(body['candidates']) is not list or type(body['conditions']) is not list:
        raise ValueError('station candidates and conditions must be arrays')
    candidates = tuple(require_identifier(value, 'body candidate') for value in body['candidates'])
    if len(set(candidates)) != len(candidates) or len(body['conditions']) != len(candidates) + 1:
        raise ValueError('station conditions must cover the baseline and each declared candidate once')
    conditions = tuple(
        _decode_condition(payload, candidate)
        for payload, candidate in zip(body['conditions'], (None, *candidates), strict=True)
    )
    return StationEvidence(station, round_id, revision, anchors, candidates, conditions, issue)
