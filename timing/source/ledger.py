import sqlite3

from timing.source.rounds import require_identifier


class SourceLedger:
    def __init__(self, connection: sqlite3.Connection, station_id: str):
        self.connection = connection
        self.station_id = require_identifier(station_id, 'station identity')

    def initialize(self) -> None:
        db = self.connection
        if db.in_transaction:
            raise sqlite3.ProgrammingError('source initialization requires an idle connection')
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS source_station (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                station_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_rounds (
                round_id TEXT PRIMARY KEY,
                first_anchor TEXT NOT NULL,
                second_anchor TEXT NOT NULL,
                CHECK (first_anchor <> second_anchor)
            );
            CREATE TABLE IF NOT EXISTS source_vouchers (
                round_id TEXT NOT NULL REFERENCES source_rounds(round_id),
                voucher_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                label TEXT NOT NULL,
                withdrawable INTEGER NOT NULL CHECK (withdrawable IN (0, 1)),
                PRIMARY KEY (round_id, voucher_id),
                UNIQUE (round_id, position)
            );
            CREATE TABLE IF NOT EXISTS source_revisions (
                revision_id INTEGER PRIMARY KEY,
                round_id TEXT NOT NULL REFERENCES source_rounds(round_id),
                parent_id INTEGER,
                UNIQUE (revision_id, round_id),
                FOREIGN KEY (parent_id, round_id)
                    REFERENCES source_revisions(revision_id, round_id)
            );
            CREATE TABLE IF NOT EXISTS source_observations (
                revision_id INTEGER NOT NULL,
                round_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                start_event TEXT NOT NULL,
                end_event TEXT NOT NULL,
                numerator TEXT NOT NULL,
                denominator TEXT NOT NULL,
                voucher_id TEXT NOT NULL,
                PRIMARY KEY (revision_id, position),
                FOREIGN KEY (revision_id, round_id)
                    REFERENCES source_revisions(revision_id, round_id),
                FOREIGN KEY (round_id, voucher_id)
                    REFERENCES source_vouchers(round_id, voucher_id)
            );
        ''')
        db.execute('BEGIN IMMEDIATE')
        with db:
            stored = db.execute('SELECT station_id FROM source_station WHERE singleton = 1').fetchone()
            if stored is None:
                db.execute('INSERT INTO source_station VALUES (1, ?)', (self.station_id,))
            elif stored[0] != self.station_id:
                raise ValueError(f'source database belongs to station {stored[0]!r}')

    def insert_round(self, round_id, anchors, vouchers) -> None:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            current = self.fetch_round(round_id)
            if current is not None:
                if current != (anchors, vouchers):
                    raise ValueError(f'round {round_id!r} already has a different specification')
                return
            db.execute('INSERT INTO source_rounds VALUES (?, ?, ?)', (round_id, *anchors))
            db.executemany(
                'INSERT INTO source_vouchers VALUES (?, ?, ?, ?, ?)',
                ((round_id, key, position, label, enabled)
                 for position, (key, label, enabled) in enumerate(vouchers)),
            )

    def insert_revision(self, round_id, parent_id, observations) -> int:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            cursor = db.execute(
                'INSERT INTO source_revisions (round_id, parent_id) VALUES (?, ?)',
                (round_id, parent_id),
            )
            revision_id = cursor.lastrowid
            db.executemany(
                'INSERT INTO source_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                ((revision_id, round_id, position, *row) for position, row in enumerate(observations)),
            )
        return revision_id

    def fetch_round(self, round_id):
        db = self.connection
        anchors = db.execute(
            'SELECT first_anchor, second_anchor FROM source_rounds WHERE round_id = ?', (round_id,)
        ).fetchone()
        if anchors is None:
            return None
        vouchers = db.execute(
            '''SELECT voucher_id, label, withdrawable FROM source_vouchers
               WHERE round_id = ? ORDER BY position''',
            (round_id,),
        )
        return tuple(anchors), tuple((key, label, bool(enabled)) for key, label, enabled in vouchers)

    def fetch_revision(self, revision_id):
        db = self.connection
        header = db.execute(
            'SELECT round_id, parent_id FROM source_revisions WHERE revision_id = ?', (revision_id,)
        ).fetchone()
        if header is None:
            return None
        rows = db.execute(
            '''SELECT start_event, end_event, numerator, denominator, voucher_id
               FROM source_observations WHERE revision_id = ? ORDER BY position''',
            (revision_id,),
        )
        return header[0], header[1], tuple(tuple(row) for row in rows)
