# 复测时差设定单

## 计时口径

轮次登记的首锚和末锚分别承担 U、V 的角色，名称沿用该轮登记。以 U 为零点，私有事件时刻允许取本站正有理刻度的任意整数倍，包含负拍。V 的时刻就是待核定的公共时差，可以连续取值。对一个候选时差，每站须能给自己全部私有事件同时安排时刻，使该固定修订的全部观察成立。每行 `Observation(start, end, upper_ms, voucher_id)` 仍表示 `t(end) - t(start) <= upper_ms`。V2 使用不撤单条件，包含与公共锚分离的观察分量。两站的私有时刻各自独立，同一次设定在两站共用同一个公共时差。

刻度和时间窗沿用 `parse_rational_ms` 的精确毫秒输入口径。窗为有限闭窗 `0 <= lo_ms <= hi_ms`，可为单点。端点相等照计。已登记的两站刻度可以不同。

## 调用

沿用 README.md 的站库、实收库和档案库初始化方式。调用者持有连接，从空闲连接发起写入。

| 办理 | Python 入口及结果 |
| --- | --- |
| 发行及补领 | `timing.issue.publish.StationPublisher.publish_v2(revision_id, tick_ms)` 返回 V2 JSON 文本。`get_issued_v2(issue_id)` 按已发编号读取该 V2 原文本，站库重开后可照常领取。 |
| 实收 | `timing.intake.receipts.accept_station_v2(store, text)` 返回既有 `Receipt` 类型。同站同发行号的等价 JSON 重投复用首次实收号，保留累计重投语义。 |
| 签设定单 | `timing.review.tick_window.sign_tick_window(archive, receipt_ids, lo_ms, hi_ms)` 凭两个不同的有序实收号及窗口签单。来件须均为 V2，同轮、异站，且登记锚序相同。计算仅使用中心实收的这两份站件。 |
| 领取 | `timing.archive.readback.read_tick_window(archive, report_id)` 读取已存设定单。在中心重开或追加勘误后，仍可按原号读取同一结论和出处。 |

签发和领取都返回 `TickWindowReport`，包含 `report_id`、`commit_receipt_id`、`lo_ms`、`hi_ms`、`earliest_ms` 和 `sources`。窗界及合格时差为 `Fraction`。`sources` 为实际双件的有序 `StationProvenance` 对，含实收号、站点、发行号、轮次和修订号。无共同可行值时 `earliest_ms` 为 `None`，仍签定稿和回执。请求、实际有序出处、结论和回执同次提交，任何写入失败整体回滚并保留原异常，可重办。非法输入、坏件、混版、同发行号异文及来件配对错误抛出 `ValueError`。格式合法的未知编号抛出 `KeyError`。

V2 外层沿用站件身份字段 `station_id`、`issue_id`、`revision_id`，携带整数 `version` 为 2 和对象 `body`。正文重复绑定这四项身份，并带 `anchors` 和正有理 `tick_ms`。线上的刻度用最简 `[整数分子, 正整数分母]`。时差资格的正文编码由实现确定，发行与验收使用同一口径，原观察行及私有事件名保存在站端。来件须核对正文与外层的身份、证据格式和数值。站点发行号及中心实收号分别沿现有编号空间，V1 入口、来件和已签报告照常办理。

正文的时差资格包含 `status`、`bounds` 和 `phases`：`status` 为 `conflict` 时后两者均为 `null`；为 `feasible` 时 `bounds` 给出连续上下界（无限端为 `null`），`phases` 是单位圆上可行分数相位的闭切片数组，空数组表示任意分数相位均可行。每个切片通常是两个最简有理端点 `[lo, hi]`，端点均在 `[0, 1)` 内；`lo <= hi` 为普通切片，`lo > hi` 为穿过原点的环绕切片，含义是 `[lo, 1) ∪ {0} ∪ [0, hi]`。当环绕切片不含原点（仅 `[lo, 1)`）时，追加第三个布尔元素 `false`；省略该元素或给 `true` 均表示含原点。两等端点的普通切片表示孤立可行拍。

## 班次样例与运行

`samples/tick_window.json` 的 `revisions` 按登记顺序列出站点、刻度、观察和可选父修订。`orders` 按实际选件顺序引用这些修订。`v1_bounds_ms` 为连续旧账的上下界，`null` 代表该侧无界。`windows` 每行依次给出新工单的下界、上界和手算最早值，第三项的 `null` 表示空设定单。`python3 -B tick_window_sample.py` 从同一份原观察跑通现有 V1 发行、实收、签存和领取，核对连续口径及原出处。

样例的北台同刻件仅允许整数毫秒，晚半拍件仅允许整数毫秒再加半拍。追加绝对下界后，半拍件在 `[1/2,3/2]` 内最早为 `3/2`。两台异刻度的工单中，南台允许 `1/2 + 3k/2` 毫秒，`k` 为整数。它与北台同刻件在 `[0,1]` 内无共同值，在 `[0,2]` 内最早为 `2`，`[2,2]` 也可签 `2`。孤立版增添两个恰差半拍的私有事件，按北台整拍口径无解。

交付继续使用项目根目录的 `.pointwise-runtime.json`，保留 `version` 为 1 和 `kind` 为 `cli`。`setup` 保存准备命令的 argv 列表，`verify` 和 `demo` 各保存一条 argv。核验入口执行完整原回归及新版业务核验，核验不符时以非零状态退出。演示入口展示同一闭窗的同刻和晚半拍两版办理结果，以及站库关闭、中心重开后的按号领取。样例中的异刻度、孤立分量和绝对下界可用于核对同一签发口径。
