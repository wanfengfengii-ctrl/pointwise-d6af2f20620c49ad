# 河湾水样双路供样试验台账

河湾水样比对试验室用这个台账核定两条支路在同一工况中的供样率。白班持有配管原测，夜班按指定站件签发通过或补测报告，主管按号核对勘误前后的定稿。站内通路可能在同一工况一起成立，也可能轮换出现。合网后还可能从一站出发，经另一站返回原站。

## 一天的交班

1. 白班登记试验轮和两站公开端口清册。同轮同名端口表示同一接头。
2. 白班导入管段、各工况下的活管段和精确权重。原测按不可变修订保存。
3. 白班按两份指定修订发行站件，固定公开连通证据和出处。
4. 白班关源后，夜班凭已登记清册实收站件。同件重投沿用原号。
5. 夜班指定两个实收号、供样入口、两条支路及放行线。
6. 中心在每对同时发生的站内工况上拼网，核定双路共同可达的精确概率。报告和成功回执共同入账，补测班按裁决行动。
7. 白班发现北站记录有误时提交完整勘误版。夜班实收并用勘误件另签，原版仍可使用。
8. 主管重开中心账，按报告号领取固定定稿和原回执。

## 运行

使用 Python 3.11 标准库。在项目目录执行平台提供的完整回归入口。

```text
python3 -B check_project.py
```

实际交班演示使用临时目录，结束后清理数据库。

```text
python3 -B demo.py
```

演示以 `1/2` 为放行线，初版报 `1/2` 并通过，勘误版报 `3/8` 并安排补测。出错时进程返回非零。样例中南站 `A–B` 以 `1/4` 连通。北站初版全通和全断各占一半。勘误版全通以及三种恰有一对连通各占 `1/4`。勘误的全通工况贡献 `1/4`，两个可由南站接续的单对工况各贡献 `1/16`。

## Python 接口

调用方持有三个独立的 `sqlite3.Connection`。在清册账调用 `catalog.initialize_trials`，在源账调用 `observations.initialize_revisions`、`station.initialize_issuance`，在中心账调用 `receipt.initialize_receipts`、`report.initialize_decisions`。采用 SQLite 普通连接，每个写入口拥有自己的事务，使用无待提交写入的连接。初始化可以重复执行并保留原记录。清册可在原测库关闭后使用。

| 入口 | 输入与结果 |
| --- | --- |
| `catalog.register(trials, round_id, stations)` | `stations` 为两个不同站名到公开端口集合的映射，每站最多四个端口。返回冻结的 `TrialRecord`，相同清册可重登。 |
| `observations.ingest(trials, source, round_id, station, segments, circuits, *, parent_id=None)` | 输入 `PipeSegment(name, left, right)` 和 `LiveCircuit(observation_id, active, mass)` 序列。`active` 为本版活管段名的元组、列表或集合。返回具有 `revision_id` 的冻结 `Revision`。父版属于同轮同站，勘误提交整版。 |
| `station.issue(trials, source, round_id, station, revision_id)` | 返回 `IssuedPiece`，包含 `issuance_id` 和可离线交付的 JSON `payload`。重取同版返回原件。 |
| `receipt.receive(trials, center, payload)` | 校验 V1 站件的出处和正文，返回本地实收整数号。同一发行身份和内容再次交付获得原号。 |
| `report.sign(trials, center, receipt_ids, entry, targets, threshold)` | `receipt_ids` 为两个同轮异站的实收号，顺序写入父件，`targets` 为两条不同的公开支路。返回 `(Decision, SuccessReceipt)`。 |
| `report.read(center, report_id)` | 返回签存的 `(Decision, SuccessReceipt)`。`Decision` 含原请求、有序父件、`Fraction` 概率和 `pass` 或 `retest` 裁决。 |

轮、站、端口、管段、顶点和工况名使用非空可打印字符串，按原值区分。工况号及管段名在一版内各自唯一。权重和放行线接受 `Fraction`、整数或可由 `Fraction` 解析的字符串，例如 `1/4`。放行线在 `[0, 1]`，概率相等时通过。活管段表示无向连接，空活管段表示全部隔离，入口到自身的零段路径可达。工况权重无量纲，可为零。站点工况彼此独立，计算为确定性枚举。

站件 V1 外层含 `version`、`issuance_id`、`round_id`、`station`、`revision_id`、`ports` 和 `rows`。每行的 `blocks` 是该站全部公开端口的一个完整划分，端口在块内排序，块及证据行也按字典序固定。`mass` 为整数分子和正整数分母组成的数组。发行时相同划分合并，省略零质量行。原工况号与私有连接留在源账。各轮各站使用自己的权威源账。发行号由轮、站、修订号稳定导出，中心的出处核对依赖固定清册及可信交付渠道。

非法值、冲突重登、同号异正文和错件组合抛出 `ValueError`。未知或错属的轮、站、修订、实收号和报告号抛出 `LookupError`。SQLite 写入失败向调用方报告原异常。校验拒绝不留下部分修订、实收或定稿，签存失败同时回滚报告及成功回执。历史领取仅访问中心定稿和回执记录。
