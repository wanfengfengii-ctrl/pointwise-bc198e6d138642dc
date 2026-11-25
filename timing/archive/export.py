from timing.archive.readback import ReportReadback
from timing.issue.intervals import TimeInterval


def _format_interval(interval: TimeInterval | None) -> str:
    if interval is None:
        return '矛盾，继续复测'
    lower = '(-∞' if interval.lower is None else f'[{interval.lower}'
    upper = '+∞)' if interval.upper is None else f'{interval.upper}]'
    return f'{lower},{upper} ms'


def format_handover(readback: ReportReadback) -> str:
    report = readback.report
    result = report.draft.result
    start, end = result.request.anchors
    lines = [
        f'报告 {report.report_id}，定稿回执 {readback.receipt.receipt_id}',
        f'轮次 {readback.sources[0].round_id}，锚向 {start}→{end}',
    ]
    for position, source in enumerate(readback.sources, 1):
        lines.append(
            f'来件 {position} {source.station_id}，实收 {source.receipt_id}，'
            f'发行 {source.issue_id}，修订 {source.revision_id}'
        )
    for outcome in result.outcomes:
        label = '不撤单' if outcome.voucher_id is None else f'撤 {outcome.voucher_id}'
        lines.append(f'{label} {_format_interval(outcome.interval)}')
    return '\n'.join(lines)


def export_handover(readback: ReportReadback) -> str:
    return format_handover(readback) + '\n'
