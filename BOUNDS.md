# 区间权重的双路供样交班

## 白班登记与站件发行

三本账的连接及初始化方式见 README.md。继续使用固定的两站清册，同轮同名公开端口表示同一接头。

新增 `observations.ingest_bounds(trials, source, round_id, station, segments, circuits, *, parent_id=None)`。参数沿用 `ingest`，其中 `circuits` 的各项为 `(工况号, 活管段, 下界, 上界)`。沿用原工况名、管段、活管段及父版规则，勘误登记完整一版。上下界接受 `Fraction`、整数及可解析的有理数字符串，布尔值和浮点数非法。允许相等的端点及零权重，要求 `0 ≤ 下界 ≤ 上界 ≤ 1`，且同站存在一组使权重和恰为一的取值。返回具有 `.revision_id` 的固定修订。站库重开后仍能按该号发行，修改调用方原对象不影响已登记内容。

`station.issue(trials, source, round_id, station, revision_id)` 同时服务点权与区间修订，仍返回含 `issuance_id` 和 JSON `payload` 的 `IssuedPiece`。同一修订再次发行交付原件。区间站件使用独立版本，JSON 外层保留 `version`、`issuance_id`、`round_id`、`station`、`revision_id`、`ports` 绑定字段。保留旧发行身份及V1站件编码。区间证据正文由实现定义。

每个公开划分是同一工况下的公开端口连通分组，沿用V1的合网含义。同一划分的不同原工况都贡献该划分质量。站件表示的分布必须完整覆盖所有可实现分布，而且其中每套分布都能在该修订的原工况区间内实现。原工况号、私有顶点和私有管段留在站库。

## 夜班实收与签报

`receipt.receive(trials, center, payload)` 离线接纳两种站件，仍返回本地实收整数号。沿用V1的可信交付渠道。中心核对站件结构、轮站修订及发行身份绑定、清册、完整划分和可行域。坏件和同号异正文拒收，同件重投保持原实收号。仅改变JSON空白或对象键顺序仍是同件。

新增 `report.sign_bounds(trials, center, receipt_ids, entry, targets, threshold)`，参数与 `report.sign` 相同。按本次列出的实收号及顺序核定两个同轮异站件。V1件视为只有一个可选分布。对任意两站合法分布按独立性取乘积，用原全网可达规则判断入口能否同时通到两个目标。每站的整套分配同时用于所有组合。在这些可实现的供样率中取最小值和最大值。

返回 `(BoundsDecision, SuccessReceipt)`。`BoundsDecision` 包含 `report_id`、`request`、`parents`、`verdict`，其含义沿用 `Decision`。`lower` 和 `upper` 是 `Fraction`。`lower_witness` 和 `upper_witness` 分别为二元组，按 `parents` 顺序各给一套该站公开分配。每套分配为按划分字典序排列的 `(blocks, mass)` 元组序列，`blocks` 沿用V1排序，`mass` 为 `Fraction`。各划分只列一次，允许省略零质量项，未列项按零核算。对每个端点，用所附两套分配回代须恰得该端点。有多个达界见证可任选一个。下界达到放行线时为 `pass`，否则为 `retest`。

`report.sign` 保持原点值报告语义，收到区间件抛 `ValueError`。`report.read(center, report_id)` 可领取两种报告及各自的原成功回执。原请求、有序父件、端点和见证随定稿保存。领取只读取中心保存的定稿和回执。后续源修订、再次签发或重开中心账均保留原定稿。

沿用 README.md 的错误边界。非法值、证据正文和错件组合抛 `ValueError`，未知或错属的轮、站、修订、实收号和报告号沿用相应入口的 `LookupError`。校验拒绝保全旧账，SQLite 写入失败原样传播，报告与回执一起提交或一起回滚，失败后可重试。允许全量重算。原接口、原数据及完整原回归继续有效。

## 输入口径和手算样例

`bounds_examples.py` 提供清册、管段及五组输入。请求入口为P，目标为A和B。`EXAMPLES` 的每行依次给出样例名、北站工况、南站工况、放行线、预期范围和裁决。`SOUTH_POINT` 由V1 `ingest` 登记，其余样例工况使用 `ingest_bounds`。使用同一组管段时，两站各只通一条且分属不同支路才共同供样。仅运行 `python3 -B bounds_examples.py` 会走已有的完整名义值链路，核对关源后点值签报为 `3/4 pass`，并核对原定稿可领取。

- `merged` 的两条北站A工况都取下界时，北站A质量为1/2，剩余1/2由B承担。两条A都取上界时，B为零，北站A质量为一。南站固定B，所得范围为 `[1/2,1]`，应补测。
- `point` 固定北站A的两笔质量各为3/8，B为1/4，范围为 `[3/4,3/4]`，阈值等于下界，通过。
- `shared` 中北站A、B各半。南站在A、B间怎样分配，互补成功的总质量都为1/2。
- `two-bounds` 的两站A质量分别为 `[1/2,1]` 和 `[1/4,3/4]`。北站全给A时，南站A分别取3/4和1/4即可达到下界1/4和上界3/4。
- `four-ways` 的北站有只通A、只通B、全断、全通四类，每类最多1/2。南站固定B。北站把质量全分给只通B与全断可达零，全分给只通A与全通可达一。

## 交班核验

保留 `python3 -B check_project.py` 和原演示。交付时沿用 `.pointwise-runtime.json` 的 `version` 1、`kind` `cli`。`setup` 记录准备命令的参数数组列表，无准备步骤可为空。`verify` 和 `demo` 分别记录可执行命令的参数数组。核验入口运行原回归并核对新区间签报，含达界分配回代、拒收保全旧账及重开领取，失败以非零退出。演示入口展示实际断源实收、区间裁决及重开后按原号领取。
