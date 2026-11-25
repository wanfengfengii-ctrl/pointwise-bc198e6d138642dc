import sqlite3


class ArchiveStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        db = self.connection
        if db.in_transaction:
            raise sqlite3.ProgrammingError('archive initialization requires an idle connection')
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS report_parents (
                report_id INTEGER NOT NULL REFERENCES reports(report_id),
                position INTEGER NOT NULL CHECK (position IN (0, 1)),
                intake_id INTEGER NOT NULL REFERENCES intake_receipts(receipt_id),
                PRIMARY KEY (report_id, position),
                UNIQUE (report_id, intake_id)
            );
            CREATE TABLE IF NOT EXISTS commit_receipts (
                receipt_id INTEGER PRIMARY KEY,
                report_id INTEGER NOT NULL UNIQUE REFERENCES reports(report_id)
            );
            CREATE TABLE IF NOT EXISTS tick_window_reports (
                report_id INTEGER PRIMARY KEY,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tick_window_parents (
                report_id INTEGER NOT NULL REFERENCES tick_window_reports(report_id),
                position INTEGER NOT NULL CHECK (position IN (0, 1)),
                intake_id INTEGER NOT NULL REFERENCES intake_receipts(receipt_id),
                PRIMARY KEY (report_id, position),
                UNIQUE (report_id, intake_id)
            );
            CREATE TABLE IF NOT EXISTS tick_window_commit_receipts (
                receipt_id INTEGER PRIMARY KEY,
                report_id INTEGER NOT NULL UNIQUE REFERENCES tick_window_reports(report_id)
            );
        ''')

    def insert_report(self, content: str, parent_ids: tuple[int, int]) -> int:
        db = self.connection
        if not db.in_transaction:
            raise sqlite3.ProgrammingError('report insertion requires a signing transaction')
        cursor = db.execute('INSERT INTO reports (content) VALUES (?)', (content,))
        report_id = cursor.lastrowid
        db.executemany(
            'INSERT INTO report_parents VALUES (?, ?, ?)',
            ((report_id, position, number) for position, number in enumerate(parent_ids)),
        )
        return report_id

    def insert_receipt(self, report_id: int) -> int:
        db = self.connection
        if not db.in_transaction:
            raise sqlite3.ProgrammingError('receipt insertion requires a signing transaction')
        cursor = db.execute('INSERT INTO commit_receipts (report_id) VALUES (?)', (report_id,))
        return cursor.lastrowid

    def insert_tick_window(self, content: str, parent_ids: tuple[int, int]) -> tuple[int, int]:
        db = self.connection
        if not db.in_transaction:
            raise sqlite3.ProgrammingError('tick window insertion requires a signing transaction')
        report_id = db.execute(
            'INSERT INTO tick_window_reports (content) VALUES (?)', (content,)
        ).lastrowid
        db.executemany(
            'INSERT INTO tick_window_parents VALUES (?, ?, ?)',
            ((report_id, position, number) for position, number in enumerate(parent_ids)),
        )
        receipt_id = db.execute(
            'INSERT INTO tick_window_commit_receipts (report_id) VALUES (?)', (report_id,)
        ).lastrowid
        return report_id, receipt_id

    def fetch_tick_window_by_report(self, report_id: int):
        return self.connection.execute(
            '''SELECT tick_window_reports.report_id, tick_window_reports.content,
                      tick_window_commit_receipts.receipt_id,
                      left_parent.intake_id, right_parent.intake_id
               FROM tick_window_reports
               JOIN tick_window_commit_receipts USING (report_id)
               JOIN tick_window_parents AS left_parent
                    ON left_parent.report_id = tick_window_reports.report_id
                   AND left_parent.position = 0
               JOIN tick_window_parents AS right_parent
                    ON right_parent.report_id = tick_window_reports.report_id
                   AND right_parent.position = 1
               WHERE tick_window_reports.report_id = ?''',
            (report_id,),
        ).fetchone()

    def _fetch(self, predicate: str, number: int):
        # Both callers supply fixed column names for their respective identifier space.
        return self.connection.execute(
            f'''SELECT reports.report_id, reports.content, commit_receipts.receipt_id,
                       left_parent.intake_id, right_parent.intake_id
                FROM reports JOIN commit_receipts USING (report_id)
                JOIN report_parents AS left_parent
                     ON left_parent.report_id = reports.report_id AND left_parent.position = 0
                JOIN report_parents AS right_parent
                     ON right_parent.report_id = reports.report_id AND right_parent.position = 1
                WHERE {predicate} = ?''',
            (number,),
        ).fetchone()

    def fetch_by_report(self, report_id: int):
        return self._fetch('reports.report_id', report_id)

    def fetch_by_receipt(self, receipt_id: int):
        return self._fetch('commit_receipts.receipt_id', receipt_id)
