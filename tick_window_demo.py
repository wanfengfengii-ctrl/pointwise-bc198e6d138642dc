"""V2 tick-window business demonstration.

Runs entirely from ``samples/tick_window.json`` with fresh SQLite databases in
a temporary directory: each station publishes V2 documents against its own
positive rational tick, the center accepts them after the stations close,
signs every closed window (including the two versions of the same window and
the cross-tick, isolated-component and absolute-lower-bound cases), then the
center is reopened and the stored settings are collected by report number.
"""

import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from timing.archive.archive_store import ArchiveStore
from timing.archive.tick_readback import read_tick_window
from timing.intake.receipt_store import ReceiptStore
from timing.intake.receipts import accept_station_v2
from timing.intake.v2_envelope import canonical_v2_envelope
from timing.issue.publish import StationPublisher
from timing.review.tick_window import sign_tick_window
from timing.source.ledger import SourceLedger
from timing.source.observations import Observation
from timing.source.revisions import register_round, save_revision
from timing.source.rounds import RoundSpec
from timing.source.vouchers import Voucher

SAMPLE = Path(__file__).resolve().parent / 'samples' / 'tick_window.json'


def _open_station(path: Path, name: str, sample: dict):
    connection = sqlite3.connect(path)
    ledger = SourceLedger(connection, name)
    ledger.initialize()
    publisher = StationPublisher(ledger)
    publisher.initialize()
    register_round(
        ledger,
        RoundSpec(sample['round_id'], tuple(sample['anchors'])),
        [Voucher(*row) for row in sample['vouchers']],
    )
    return connection, ledger, publisher


def _rational_text(value) -> str:
    return 'null' if value is None else str(Fraction(value))


def main() -> int:
    sample = json.loads(SAMPLE.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='linchuan-tick-') as temporary:
        root = Path(temporary)
        issues: dict[str, object] = {}
        receipts: dict[str, int] = {}
        station_paths: dict[str, Path] = {}

        # Day shift: each station database is opened, populated and closed.
        connections: dict[str, sqlite3.Connection] = {}
        publishers: dict[str, StationPublisher] = {}
        for name, spec in sample['revisions'].items():
            station = spec['station']
            if station not in connections:
                path = root / f'{station}.sqlite'
                station_paths[station] = path
                connections[station], _, publishers[station] = _open_station(path, station, sample)
            publisher = publishers[station]
            parent = issues[spec['parent']].revision_id if 'parent' in spec else None
            revision_id = save_revision(
                publisher.ledger,
                sample['round_id'],
                (Observation(*row) for row in spec['rows']),
                parent,
            )
            envelope = publisher.publish_v2(revision_id, Fraction(spec['tick_ms']))
            issues[name] = envelope

        # Night shift: stations are closed before the center accepts anything.
        for connection in connections.values():
            connection.close()
        for name, envelope in issues.items():
            # Reopening proves get_issued_v2 still serves the stored original.
            with closing(sqlite3.connect(station_paths[envelope.station_id])) as reopened:
                ledger = SourceLedger(reopened, envelope.station_id)
                ledger.initialize()
                publisher = StationPublisher(ledger)
                publisher.initialize()
                assert publisher.get_issued_v2(envelope.issue_id) == envelope

        center_path = root / 'center.sqlite'
        center = sqlite3.connect(center_path)
        intake = ReceiptStore(center)
        intake.initialize()
        archive = ArchiveStore(center)
        archive.initialize()
        for name, envelope in issues.items():
            receipts[name] = accept_station_v2(intake, canonical_v2_envelope(envelope)).receipt_id

        signed: list[dict] = []
        for order in sample['orders']:
            pair = tuple(receipts[name] for name in order['revisions'])
            for lo_ms, hi_ms, expected in order['windows']:
                report = sign_tick_window(archive, pair, lo_ms, hi_ms)
                actual = _rational_text(report.earliest_ms)
                wanted = 'null' if expected is None else str(Fraction(expected))
                if actual != wanted:
                    raise AssertionError(
                        f'{order["id"]} window [{lo_ms}, {hi_ms}] gave {actual}, expected {wanted}'
                    )
                signed.append({
                    'order': order['id'],
                    'window': [lo_ms, hi_ms],
                    'report_id': report.report_id,
                    'commit_receipt_id': report.commit_receipt_id,
                    'earliest_ms': actual,
                    'receipts': list(pair),
                    'stations': [source.station_id for source in report.sources],
                })
        center.close()

        # Reopen the center and retrieve every stored setting by report number.
        with closing(sqlite3.connect(center_path)) as reopened_center:
            intake_two = ReceiptStore(reopened_center)
            intake_two.initialize()
            archive_two = ArchiveStore(reopened_center)
            archive_two.initialize()
            readback = []
            for item in signed:
                stored = read_tick_window(archive_two, item['report_id'])
                if stored.commit_receipt_id != item['commit_receipt_id']:
                    raise AssertionError('commit receipt changed after center reopen')
                if _rational_text(stored.earliest_ms) != item['earliest_ms']:
                    raise AssertionError('earliest value changed after center reopen')
                if [source.receipt_id for source in stored.sources] != item['receipts']:
                    raise AssertionError('ordered provenance changed after center reopen')
                readback.append({
                    'report_id': stored.report_id,
                    'commit_receipt_id': stored.commit_receipt_id,
                    'lo_ms': str(stored.lo_ms),
                    'hi_ms': str(stored.hi_ms),
                    'earliest_ms': _rational_text(stored.earliest_ms),
                    'sources': [
                        {
                            'receipt_id': source.receipt_id,
                            'station_id': source.station_id,
                            'issue_id': source.issue_id,
                            'round_id': source.round_id,
                            'revision_id': source.revision_id,
                        }
                        for source in stored.sources
                    ],
                })

    print('TICK_WINDOW_PUBLISH ' + json.dumps({
        'round_id': sample['round_id'],
        'issues': {
            name: {
                'station': envelope.station_id,
                'issue_id': envelope.issue_id,
                'revision_id': envelope.revision_id,
                'version': envelope.version,
            }
            for name, envelope in issues.items()
        },
        'receipts': receipts,
    }, ensure_ascii=False, sort_keys=True))
    for item in signed:
        print('TICK_WINDOW_SIGN ' + json.dumps(item, ensure_ascii=False, sort_keys=True))
    for item in readback:
        print('TICK_WINDOW_READBACK ' + json.dumps(item, ensure_ascii=False, sort_keys=True))
    print('TICK_WINDOW_DEMO OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
