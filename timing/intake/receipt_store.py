import sqlite3


class ReceiptStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        db = self.connection
        if db.in_transaction:
            raise sqlite3.ProgrammingError('receipt initialization requires an idle connection')
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('''
            CREATE TABLE IF NOT EXISTS intake_receipts (
                receipt_id INTEGER PRIMARY KEY,
                station_id TEXT NOT NULL,
                issue_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                replay_count INTEGER NOT NULL DEFAULT 0 CHECK (replay_count >= 0),
                UNIQUE (station_id, issue_id)
            )
        ''')

    def record_delivery(self, station_id: str, issue_id: int, content: str) -> tuple[int, int]:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            stored = db.execute(
                '''SELECT receipt_id, content, replay_count FROM intake_receipts
                   WHERE station_id = ? AND issue_id = ?''',
                (station_id, issue_id),
            ).fetchone()
            if stored is None:
                inserted = db.execute(
                    'INSERT INTO intake_receipts (station_id, issue_id, content) VALUES (?, ?, ?)',
                    (station_id, issue_id, content),
                )
                return inserted.lastrowid, 0
            receipt_id, previous_content, replay_count = stored
            if previous_content != content:
                raise ValueError(f'conflicting content for station {station_id!r} issue {issue_id}')
            db.execute(
                'UPDATE intake_receipts SET replay_count = replay_count + 1 WHERE receipt_id = ?',
                (receipt_id,),
            )
            return receipt_id, replay_count + 1

    def fetch_receipt(self, receipt_id: int) -> tuple[str, int] | None:
        stored = self.connection.execute(
            'SELECT content, replay_count FROM intake_receipts WHERE receipt_id = ?', (receipt_id,)
        ).fetchone()
        return None if stored is None else (stored[0], stored[1])
