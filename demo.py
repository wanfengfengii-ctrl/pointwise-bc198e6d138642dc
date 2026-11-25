import argparse
import json
import sqlite3
import sys
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from timing.archive.archive_store import ArchiveStore
from timing.archive.commit import commit_report
from timing.archive.export import export_handover
from timing.archive.readback import read_by_receipt, read_by_report
from timing.archive.reports import build_report_draft
from timing.intake.checks import verify_station
from timing.intake.receipt_store import ReceiptStore
from timing.intake.receipts import accept_station
from timing.issue.publish import StationPublisher
from timing.review.joint import review_pair
from timing.review.request import ReviewRequest
from timing.source.ledger import SourceLedger
from timing.source.observations import Observation
from timing.source.revisions import register_round, save_revision
from timing.source.rounds import RoundSpec
from timing.source.vouchers import Voucher


SAMPLES = Path(__file__).resolve().parent / 'samples'


def load_case(name):
    if name not in ('shift', 'crossed'):
        raise ValueError(f'unknown demonstration case {name!r}')
    return json.loads((SAMPLES / f'{name}.json').read_text(encoding='utf-8'))


@contextmanager
def open_station(path, name):
    with closing(sqlite3.connect(path)) as connection:
        ledger = SourceLedger(connection, name)
        ledger.initialize()
        publisher = StationPublisher(ledger)
        publisher.initialize()
        yield ledger, publisher


@contextmanager
def open_center(path):
    with closing(sqlite3.connect(path)) as connection:
        intake = ReceiptStore(connection)
        intake.initialize()
        archive = ArchiveStore(connection)
        archive.initialize()
        yield intake, archive


def stage_revision(ledger, publisher, case, rows, parent_id=None):
    spec = RoundSpec(case['round_id'], tuple(case['anchors']))
    register_round(ledger, spec, (Voucher(*row) for row in case['vouchers']))
    revision = save_revision(ledger, spec.round_id, (Observation(*row) for row in rows), parent_id)
    return publisher.publish(revision)


def capture_pair(root, intake, case):
    with ExitStack() as sources:
        issues = []
        receipt_ids = []
        for name in ('north', 'south'):
            ledger, publisher = sources.enter_context(open_station(root / f'{name}.sqlite', name))
            issued = stage_revision(ledger, publisher, case, case[name])
            issues.append(issued)
            receipt_ids.append(accept_station(intake, issued).receipt_id)
    return tuple(issues), tuple(receipt_ids)


def sign(archive, intake, request):
    return commit_report(archive, build_report_draft(review_pair(intake, request)))


def outcomes(result):
    return [
        [item.voucher_id, item.status, None if item.interval is None else item.interval.to_payload()]
        for item in result.outcomes
    ]


def emit_scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError(f'{case_id} did not match its independent expected result')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': paths, 'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


def run_shift(root):
    case = load_case('shift')
    center = root / 'center.sqlite'
    with open_center(center) as (intake, archive):
        issues, ids = capture_pair(root, intake, case)
        request = ReviewRequest(ids, case['anchors'], case['candidates'])
        previous, previous_receipt = sign(archive, intake, request)
        with open_station(root / 'north.sqlite', 'north') as (ledger, publisher):
            correction = stage_revision(
                ledger, publisher, case, case['north_correction'], issues[0].revision_id
            )
            corrected_id = accept_station(intake, correction).receipt_id
        new_ids = (corrected_id, ids[1])
        current, current_receipt = sign(
            archive, intake, ReviewRequest(new_ids, case['anchors'], case['candidates'])
        )
    with open_center(center) as (_, archive):
        old = read_by_report(archive, previous.report_id)
        new = read_by_receipt(archive, current_receipt.receipt_id)
    conflict = [None, 'conflict', None]
    last_conflict = ['B', 'conflict', None]
    old_expected = [conflict, ['A', 'feasible', {'lower': [1, 1], 'upper': [1, 1]}], last_conflict]
    new_expected = [conflict, ['A', 'feasible', {'lower': [1, 1], 'upper': [3, 2]}], last_conflict]
    north_branch = verify_station(issues[0]).evidence.conditions[1]
    north_actual = [north_branch.voucher_id, north_branch.status,
                    None if north_branch.interval is None else north_branch.interval.to_payload()]
    old_actual = outcomes(old.report.draft.result)
    new_actual = outcomes(new.report.draft.result)
    emit_scenario(
        'V4.indirect_alternative', case, ['A', 'feasible', {'lower': None, 'upper': [1, 1]}], north_actual,
        old_expected, old_actual,
        ['timing/issue/evidence.py', 'timing/review/joint.py', 'timing/archive/readback.py'],
        'On withdrawal of A the north path weighs 1/3 + 2/3 and the south reference requires d >= 1.',
    )
    emit_scenario(
        'V9.reinitialize_history', {'case': case, 'old_intake': ids, 'new_intake': new_ids},
        [old_expected, new_expected], [old_actual, new_actual],
        [list(ids), list(new_ids), previous_receipt.receipt_id, current_receipt.receipt_id, current.report_id],
        [[source.receipt_id for source in old.sources], [source.receipt_id for source in new.sources],
         old.receipt.receipt_id, new.receipt.receipt_id, new.report.report_id],
        ['timing/source/revisions.py', 'timing/archive/commit.py', 'timing/archive/readback.py'],
        'The correction changes the upper bound to 1/3 + 7/6. Each retrieval must retain the identifiers returned when it was signed.',
    )
    print(export_handover(old), end='')
    print(export_handover(new), end='')
    return 0


def run_crossed(root):
    case = load_case('crossed')
    with open_center(root / 'center.sqlite') as (intake, archive):
        _, ids = capture_pair(root, intake, case)
        request = ReviewRequest(ids, case['anchors'], case['candidates'])
        result = review_pair(intake, request)
        report, _ = commit_report(archive, build_report_draft(result))
        readback = read_by_report(archive, report.report_id)
    print(export_handover(readback), end='')
    if any(item.interval is not None for item in readback.report.draft.result.outcomes[1:]):
        print('TIME_REVIEW_FALSE_CLEAR', file=sys.stderr)
        return 1
    wanted = [[None, 'conflict', None], ['A', 'conflict', None], ['B', 'conflict', None]]
    emit_scenario(
        'V5.crossed_report', case, wanted, outcomes(result),
        [wanted, list(ids)], [outcomes(readback.report.draft.result),
                              [source.receipt_id for source in readback.sources]],
        ['timing/issue/evidence.py', 'timing/review/conditions.py', 'timing/review/joint.py',
         'timing/archive/readback.py'],
        'In either withdrawal one station requires d <= 0 and the other d >= 1; the baseline retains both.',
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description='临川仪器联试室计时复核演示')
    parser.add_argument('case', choices=('shift', 'crossed'), nargs='?', default='shift')
    arguments = parser.parse_args()
    with TemporaryDirectory(prefix='linchuan-timing-') as temporary:
        root = Path(temporary)
        return run_crossed(root) if arguments.case == 'crossed' else run_shift(root)


if __name__ == '__main__':
    raise SystemExit(main())
