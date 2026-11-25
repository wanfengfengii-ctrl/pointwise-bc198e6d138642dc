# 临川仪器联试室计时复核

北、南台架用共同的启动脉冲 U 和验收脉冲 V 对齐。夜班在两站关库后，根据指定来件核对不撤单和逐一撤单的可行时差。矛盾意味着该动作仍需复测。闭区间或单点提供复测时差依据，次班可按正式号领取历史结论。

## 班次演示与回归

使用 Python 3.11 标准库，从项目根目录执行。演示在测试临时目录内建立两个站库和一个中心库。

```sh
python3 -B demo.py
python3 -B demo.py crossed
python3 -B tick_window_demo.py
python3 -B check_project.py
```

默认演示运行 `samples/shift.json`。白班登记、发行，夜班实收并关站后签发基准矛盾、撤甲 `[1,1]`、撤乙矛盾。次班勘误后再签撤甲 `[1,3/2]`，重开中心后按旧报告号和新回执号领取。`crossed` 使用 `samples/crossed.json` 从原始观察办理交叉样例，基准及两项撤单均应矛盾。平台物化工程时提供 `check_project.py`，它运行 `tests` 包的完整原回归。

## 公开 Python 接口

站库与中心库各自使用调用者持有的 `sqlite3.Connection`。调用者负责关闭连接；初始化和业务写入从没有外部未提交事务的连接开始。`initialize()` 可以重复调用，已有资料和编号可继续使用。每个物理站库属于一个固定站点；向同一中心投递的一个站点使用该站点唯一的发行序列。

| 接口 | 调用和结果 |
| --- | --- |
| I1 | `SourceLedger(connection, station_id).initialize()` 建表。`register_round(ledger, RoundSpec(round_id, (u, v)), vouchers)` 登记该轮，`save_revision(ledger, round_id, observations, parent_id=None)` 返回修订号，`load_revision(ledger, revision_id)` 读取完整修订。`Voucher(id, label=None, withdrawable=True)` 可标记保留凭单。`Observation(start, end, upper_ms, voucher_id)` 登记一条有向约束。完全相同的轮次登记可重放。 |
| I2 | `StationPublisher(ledger).initialize()` 建发行表。`publish(revision_id, candidates=None)` 返回 `V1Envelope`；省略候选时覆盖轮次全部可撤凭单。显式列表选择覆盖范围，重复选择按首次出现归并。`get_issued_station(issue_id)` 取固定原件，`encode_envelope` 和 `decode_envelope` 用于 V1 文本交换。 |
| I3 | `ReceiptStore(center_connection).initialize()` 建实收表。`accept_station(store, envelope_or_json)` 返回 `Receipt`，含实收号、重投状态及累计重投次数。`get_received_station(store, receipt_id)` 读取原实收件。 |
| I4 | `review_pair(store, ReviewRequest((left_receipt, right_receipt), (u, v), candidates))` 只查中心库，返回 `ReviewResult`。结果从基准开始，之后逐项保留请求顺序及重复候选。两份不同站点的同轮来件须覆盖所求锚对和每个请求候选。可按反向锚查询。 |
| I5 | `ArchiveStore(center_connection).initialize()` 在实收初始化后建档案表。将 I4 返回值交给 `build_report_draft(result)`，再通过 `commit_report(archive, draft)` 签发。返回值含正式报告及其回执。 |
| I6 | `read_by_report(archive, report_id)` 或 `read_by_receipt(archive, receipt_id)` 领取存值，`export_handover(readback)` 生成交接文本。两个编号分别属于报告和定稿回执的编号空间。 |
| V2 | `StationPublisher.publish_v2(revision_id, tick_ms)` 按正有理整刻度发行 V2 站件，`get_issued_v2(issue_id)` 读取原件；`accept_station_v2(store, text)` 实收并保留同号重投语义；`sign_tick_window(archive, receipt_ids, lo_ms, hi_ms)` 凭同轮异站、锚序相同的两份 V2 实收号签发闭窗内最早共同可行值，`read_tick_window(archive, report_id)` 重开后按报告号领取。 |

相关接口按名称所在模块导入。源端入口位于 `timing.source.ledger`、`timing.source.rounds`、`timing.source.vouchers`、`timing.source.observations`、`timing.source.revisions` 和 `timing.issue.publish`。接纳及复核入口位于 `timing.intake.receipt_store`、`timing.intake.receipts`、`timing.intake.lookup`、`timing.review.request` 和 `timing.review.joint`。档案入口位于 `timing.archive.archive_store`、`timing.archive.reports`、`timing.archive.commit`、`timing.archive.readback` 和 `timing.archive.export`。

## 计算、交换与失败语义

观察 `Observation(u, v, upper, voucher)` 表示 `t(v) - t(u) <= upper`，单位为毫秒。接受整数、`Fraction` 和 Python 3.11 `Fraction` 可解析的精确数值字符串。零是有效值；布尔、浮点、缺失上界和零分母拒绝。一张凭单可支持多条边或同时出现在两站。每次试算只撤请求中的一张，移除两站中所有对应约束。全图负环使本站条件不合格，包括与公共锚不相连的私有分量。

站件是 JSON 对象，外层包含 `version`、`station_id`、`issue_id`、`round_id`、`revision_id`、`body`。正文重复绑定来件身份，包含 `anchors`、有序 `candidates` 和 `conditions`。条件首项的 `voucher_id` 为空，表示不撤单，其余逐一对应声明的候选。`status` 为 `conflict` 或 `feasible`，前者的 `interval` 为空。后者的区间包含 `lower`、`upper`，有限端用最简 `[整数分子, 正整数分母]`，无限端用 `null`。两个无限端和闭单点均是可行区间。正文不包含原观察或私有编号。中心依据同一有向锚对和同一撤单条件求两区间交集。交集中的任一有理差值可由两站分别实现，两站可整体平移以对齐两枚公共锚。

格式、用值或业务配对错误抛出 `ValueError`，未知的合法修订、发行、实收或档案编号抛出 `KeyError`。同站同发行号的等价 JSON 重投复用原号，不同内容拒绝。SQLite 写入错误按原异常传播，报告、双件出处和回执全部回滚。合法业务矛盾可正常签发。旧档领取不重算，保留原候选顺序和确切父件。
