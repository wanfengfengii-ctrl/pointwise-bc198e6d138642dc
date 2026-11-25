import sqlite3
from collections.abc import Iterable
from dataclasses import replace

from timing.intake.envelope import V1Envelope, canonical_envelope, decode_envelope
from timing.issue.evidence import build_station_evidence, encode_station_body
from timing.source.ledger import SourceLedger
from timing.source.revisions import load_revision
from timing.source.rounds import require_number
from timing.source.vouchers import resolve_candidate_vouchers


class StationPublisher:
    def __init__(self, ledger: SourceLedger):
        self.ledger = ledger

    def initialize(self) -> None:
        db = self.ledger.connection
        if db.in_transaction:
            raise sqlite3.ProgrammingError('issue initialization requires an idle connection')
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('''
            CREATE TABLE IF NOT EXISTS issued_stations (
                issue_id INTEGER PRIMARY KEY,
                revision_id INTEGER NOT NULL REFERENCES source_revisions(revision_id),
                content TEXT NOT NULL
            )
        ''')

    def publish(self, revision_id: int, candidates: Iterable[str] | None = None) -> V1Envelope:
        revision = load_revision(self.ledger, revision_id)
        selected = resolve_candidate_vouchers(revision.roster, candidates)
        evidence = build_station_evidence(revision, selected)
        db = self.ledger.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            issue_id = db.execute('SELECT COALESCE(MAX(issue_id), 0) + 1 FROM issued_stations').fetchone()[0]
            body = encode_station_body(replace(evidence, issue_id=issue_id))
            envelope = V1Envelope(revision.station_id, issue_id, revision.spec.round_id, revision_id, body)
            db.execute(
                'INSERT INTO issued_stations VALUES (?, ?, ?)',
                (issue_id, revision_id, canonical_envelope(envelope)),
            )
        return envelope

    def get_issued_station(self, issue_id: int) -> V1Envelope:
        db = self.ledger.connection
        row = db.execute(
            'SELECT content FROM issued_stations WHERE issue_id = ?',
            (require_number(issue_id, 'issue number'),),
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown issue {issue_id}')
        return decode_envelope(row[0])
