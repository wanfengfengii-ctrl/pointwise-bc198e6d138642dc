import json
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path

from demo import open_center, open_station, sign, stage_revision
from timing.archive.readback import read_by_report
from timing.intake.receipts import accept_station
from timing.issue.intervals import TimeInterval
from timing.review.request import ReviewRequest


SAMPLE = Path(__file__).resolve().parent / "samples" / "tick_window.json"


def check_v1(sample):
    issues = {}
    receipts = {}
    with open_center(":memory:") as (intake, archive):
        with ExitStack() as stations:
            sources = {
                name: stations.enter_context(open_station(":memory:", name))
                for name in ("north", "south")
            }
            for name, spec in sample["revisions"].items():
                ledger, publisher = sources[spec["station"]]
                parent_id = issues[spec["parent"]].revision_id if "parent" in spec else None
                issued = stage_revision(ledger, publisher, sample, spec["rows"], parent_id)
                issues[name] = issued
                receipts[name] = accept_station(intake, issued).receipt_id
        for order in sample["orders"]:
            ids = tuple(receipts[name] for name in order["revisions"])
            request = ReviewRequest(ids, tuple(sample["anchors"]))
            report, receipt = sign(archive, intake, request)
            stored = read_by_report(archive, report.report_id)
            values = order["v1_bounds_ms"]
            expected = TimeInterval(*(None if value is None else Fraction(value) for value in values))
            actual = stored.report.draft.result.outcomes[0].interval
            if (actual != expected or stored.receipt != receipt
                    or tuple(source.receipt_id for source in stored.sources) != ids):
                raise AssertionError(f"unexpected V1 result or source links for {order['id']}")
            print(json.dumps({"case": order["id"], "v1": actual.to_payload(), "intake": ids}, ensure_ascii=False))


if __name__ == "__main__":
    check_v1(json.loads(SAMPLE.read_text(encoding="utf-8")))
