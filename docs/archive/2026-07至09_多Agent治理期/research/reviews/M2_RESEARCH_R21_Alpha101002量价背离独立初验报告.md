# M2 Research R21 Alpha101 #002 量价背离独立初验报告

## 结论

- `REVIEW_READY`
- 审查结论：`REVIEW_FAIL`
- P0：0；P1：3；P2：0
- 实现状态上限：`IMPLEMENTED_PENDING_VALIDATION`
- 本报告仅为独立静态初验，不宣称 Python、pytest、Ruff、mypy、Linux Gate、真实数据、经济运行或收益结论通过。

## 审查边界与 exact4 现场

本 reviewer 未参与实现，固定 worktree 为
`F:\\AI_Coding\\QuantitativeTrading\\artifacts\\dev_worktrees\\m2-research-r21-alpha101-002-price-volume-divergence`，
HEAD 为 `ab78a059044d49e2d8f3e94dd5b1087f55a9f86e`。完整读取了项目 `AGENTS.md`、任务书（21341 bytes）、
exact4 交付文件及任务书第 12 节。只读检查期间未运行 Python/pytest/Ruff/mypy，未访问 data、网络、stage 或
commit；本轮仅允许写入本 review 文件。

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `src/quant/factors/classic_eleventh_batch.py` | 8450 | `7b548110eaa5db0745a691133e5f785754722da01b9e59a6ed42f76ad1c6a2de` |
| `tests/unit/test_classic_eleventh_batch.py` | 4682 | `296183a933db18a50b7d38b9d6e12398272c08bb18db39cd5d3a161ddea92020` |
| `configs/research/m2_classic_daily_factors_eleventh_batch.toml` | 2774 | `0ca63e41fa77bb36c72eaedc2b1c713169bdf9c02add6e2387aec749b574cc5b` |
| `docs/research/deliveries/M2_RESEARCH_R21_Alpha101002量价背离交付报告.md` | 1835 | `cfc1e1817900ed3f7469c04f9e63ff8e5490fa997f2be8c0f81d93595bb1e18d` |

任务书 SHA-256 为 `f15d234bb0b1861ad78b509dc354f8f9a92ce74f8ef2b4100604293a35982f0d`；交付报告诚实记录了
`VALIDATION_UNRUN / ECONOMIC_IO0 / TRIAL0`，没有把未运行状态写成绿色 Gate。

## P1 发现

### P1-1：首个 exact8 测试 fixture 必然产生零方差 volume rank，却断言三项 finite

- 现象：`tests/unit/test_classic_eleventh_batch.py:33` 令每个 symbol 的 `volume = base * (index + 1)`。
  在实数代数下 base 项会抵消，但 Float64 的乘法与 log 舍入不保证不同 base 得到逐 bit 相同结果；该 fixture 没有
  提供独立可靠的非恒定 volume-rank oracle，却直接断言三项 finite。
- 根因：任务书要求六期任一组件零方差时因子为 null，但
  `test_public_identity_exact8_and_output_contract:49` 仍断言 `drop_nulls().len() == 3`，并断言这些值 finite；现有
  fixture 无法证明该 finite 断言成立，且若按其预期全 tie 则与实现 `:170-178` 的零方差 null 门禁直接矛盾。
- 应遵循规则：测试必须同时证明 exact8 首值位置和零方差 fail-closed；不能用恒定 rank fixture 冒充可产生相关系数的
  finite fixture。
- 最小复现：保留现有 `_bars` 的 volume 公式和 8 个 sessions；检查六个有效 volume pair 的横截面 rank。若
  Float64 舍入没有制造伪差异，则 `u` 为六个 0.5、denominator 为 0，三只证券在第 8 session 均应为 null；即使出现
  舍入伪差异，也没有冻结的 exact finite oracle 可支持该断言。
- 通过条件：改为跨 symbol 具有不同、随时间变化的正 volume 序列以验证 finite exact8；另设独立 zero-variance
  测试断言 null。修复后应重新绑定 test SHA 并执行授权定向验证。

### P1-2：第 12 节要求的核心对抗矩阵没有被测试文件逐项覆盖

- 现象：测试仅覆盖 helper 调用一次/字段外形、一个内部缺 bar、duplicate/nonfinite 和四个配置字段；没有行为测试
  锁定 exact Pearson 数值与负号、ascending average ties 的 n=1/n=2/全相等、`volume=0` 局部 null、独立且不等
  component 成员集合、输入/并列行置换、session 乱序/重复/越界、exact 输出 key/dtype、公共 helper 抛错不 fallback、
  或 config 的完整 exact key/value/order 合同。
- 根因：交付报告将“成员集合/null、exact8、输入失败闭合”等概括为已新增测试，但当前 4682-byte 测试源码没有
  对应的可证伪节点；`VALIDATION_UNRUN` 也意味着不能用执行结果补足缺口。
- 应遵循规则：任务书 §10 与 §12.3/§12.4 要求真实公共 helper 的 exact-one 消费、两组件分母独立、null 保留、
  exact6 连续 Pearson 负号和第 12 节矩阵均有行为证据；字符串/测试名称不能替代实现路径证据。
- 通过条件：补齐上述行为测试，并保持 helper spy 与无 spy 真实公共调用等结果；测试不得伪造 rank 输出或只做源码检查。

## 逐项静态判定

- 公式/时间：代码显式使用 raw `volume` 的 lag-2、同日 `(close-open)/open`、symbol×sessions grid、连续六期
  rolling pair 和 `-cross/sqrt(ss*ss)`；未见 close-to-close、log1p、delta-1 或正号替代。
- 独立 component rank/public API：`classic_eleventh_batch.py:103-125` 构造一次 long-form、两个 component，调用
  `rank_cross_sectional_components` 恰好一次；未复制 rank helper，未见调用前 intersection。
- gap/null/fail-closed：grid 保留缺 bar，lag2 不跨内部洞；schema、duplicate、calendar、nonfinite 有拒绝路径；
  helper 异常直接传播，没有私有 fallback。该静态结论不等于运行验证。
- schema/output：最终列和 cast 顺序符合 `symbol, trade_date, alpha101_002`/Float64，结果 join 仅保留输入 keys。
- config：冻结 hypothesis、factor、rank/correlation、required sessions、direction、trial_delta 与经济阻断字段均在候选
  配置中出现；完整配置合同仍缺行为测试覆盖。
- 经理初读的疑点中，`Path(__file__).resolve().parents[2]` 对 `tests/unit/test_*.py` 的根目录计算是正确的；missing-bar
  测试的 `tail(1)` 也对应缺洞后的最后一个原始 key，但该测试仍未覆盖更多 gap/zero-variance 矩阵。

## 独立新增静态对抗反例（实现者未使用）

- 现象：在 8 个连续 sessions 中令一个 symbol 当日 `volume=0`，而保持该日 open/close 有效；另两个 symbol 的 volume
  正常。此时该日 `volume_change` 必须为 null，但 `intraday_return` 仍是独立组件的有效成员，两个组件的横截面分母
  必须不同；任一错误的共同 intersection 预排名会改变 intraday rank，进而改变第 8 日相关值。
- 根因：现有 tests 只检查 volume component 总 null 数，未构造“一个组件缺失而另一组件有效”的不等成员集合；因此不能
  证伪删掉另一组件成员、先取 intersection 或以 null 填 0 的实现变体。
- 应遵循规则：按任务书 §3.2/§12.3，每个 component 保留完整 symbol/session key，分别按自身 finite 成员排名；只有
  后续 exact6 pair 才要求同 symbol/date 两 rank 同时存在。
- 最小复现：三 symbol、八 sessions；某 symbol 在 session 3（或其当前 volume lag-2 依赖日）volume 设为 0，
  该日 open=close=正值；对比真实 helper 返回的两个 component rank 成员/值与共同 intersection 变体。
- 新增测试：在 `tests/unit/test_classic_eleventh_batch.py` 增加不等成员集合行为测试，spy 断言该 symbol 的
  `intraday_return` rank 非 null、`volume_change` rank 为 null，并断言真实输出不把该 pair 当 finite。
- 通过条件：公共 helper 输入 key/value schema 仍 exact，调用 exact1，未填 0、未重算 rank、未缩短窗口；该反例不应
  进入经济运行。

## 最终判定

## 补充静态裁定（同一 review 上下文）

### P1-3：intraday return 的 alias 绑定范围不满足确定的输出列合同

- 现象：`src/quant/factors/classic_eleventh_batch.py:73-76` 写成
  `(pl.col("close") - pl.col("open")) / pl.col("open").cast(pl.Float64).alias("_intraday_return")`。
  按 Python 方法绑定规则，`.cast(...).alias(...)` 只显式附着在右侧 `open` expression，而不是整个除法表达式；
  因此生产代码不能静态证明该 `with_columns` 必然产生名为 `_intraday_return` 的列，随后 `:90` 引用该列可能进入
  missing-column/contract failure。即使某个 Polars 版本传播了名称，也不能把这种未加括号的表达式视为稳定合同。
- 根因：alias 的括号范围没有覆盖完整 `(close-open)/open` 表达式。
- 应遵循规则：必须先构造完整 Float64 return expression，再对整个表达式 alias `_intraday_return`；方法绑定范围和列名
  必须静态明确，不能凭未运行输出假设正确。
- 最小复现：只按 Python AST/表达式绑定阅读上述 `with_columns`，可见 alias 位于右操作数链；后续 `pl.col("_intraday_return")`
  即是无法由源码闭合的列依赖。
- 通过条件：明确写出完整除法表达式的整体 `.cast(pl.Float64).alias("_intraday_return")`，并由定向验证证明后续
  `_intraday_return_valid` 与 long-form `intraday_return` 路径可达。当前不运行验证，故该 P1 保持。

### 对 P1-1 的措辞修正

原文“完全相同”“全为 0.5”过强：在实数代数下 `log(base*(index+1))-log(base*(index-1))` 的 base 项抵消，
但 Float64 的乘法与 log 舍入不保证不同 base 得到逐 bit 相同结果。可确定的审查结论是：该 fixture 没有提供独立可靠
的非恒定 volume-rank oracle，却断言三项 finite；它可能因浮点实现产生全 tie，也可能产生微小伪差异，均不足以证明
exact finite Pearson。应改用明确跨 symbol、跨日期且远离舍入噪声的 volume 序列，并另测 zero-variance null。

P1-1（修正后）已证明现有定向测试合同缺少可靠 oracle，P1-2 证明 §12 核心矩阵行为证据不足，P1-3 发现生产表达式
存在确定的 alias 绑定风险；因此本轮为
`REVIEW_READY / REVIEW_FAIL`。返工必须回到同一实现链，修正 fixture/断言并补齐矩阵后，由未参与实现的上下文复验。

## STATIC_REWORK 独立复验（同一 reviewer，返工后）

### 复验边界与 exact3

本轮仍未运行 Python、pytest、Ruff、mypy、data、网络、stage 或 commit；只读复验返工 production、tests、delivery，
并仅追加本 review。HEAD/worktree 身份未由本轮改写。返工 exact3 为：

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `src/quant/factors/classic_eleventh_batch.py` | 8452 | `6fe8baf1000cb8ffd5b8e58968125f3e6c4069d2e5e76af25940709351f8a4a1` |
| `tests/unit/test_classic_eleventh_batch.py` | 11081 | `482070bb83bcb3fd7588fa22e34947f4440f2f9848e44bd17e1f581201b49993` |
| `docs/research/deliveries/M2_RESEARCH_R21_Alpha101002量价背离交付报告.md` | 2788 | `fb027e164afb3719194862146e2a9391be9a5320c3f4ad4f5bacadf53bb8f74c` |

### 已闭合项

- alias 风险已修正：`((close-open)/open)` 整体先 cast，再 alias `_intraday_return`。
- 首值/公式 fixture 已改为显式六期非退化模式，并静态呈现 exact6、负号、session 8 首值和 zero-variance null。
- helper exact-one spy 与无 spy 真实调用等价；一次 long-form 同时包含两个 component，缺失值未删除另一 component key，
  helper 失败无私有 fallback。
- §10/§12 的主要矩阵节点已出现在测试源码：不等成员集合、zero volume、内部 gap、n=7/exact8、ties/n=1/n=2、
  row permutation、calendar/duplicate/nonfinite/schema、输出 contract、配置 key 顺序及阻断字段。

### P1-4：内部缺 bar 测试的行数断言与输出 key 合同矛盾

- 现象：`test_internal_gap_zero_volume_and_seven_sessions_never_bridge` 在 9 个 sessions 中省略一个
  `("600001.SH", sessions[4])`，随后按 taskbook 只保留原 bars keys 的合同，`result.filter(symbol==...).height` 应为 8；
  但测试在 `:119-121` 断言 `values.null_count() == 9`。production `keys = clean.select("symbol", "trade_date")` 和最终
  left join 明确不会补回缺失 bar，因此该断言不可能代表当前输出 contract，测试会失败（即使全部零值正确为 null）。
- 根因：返工将旧“9期全 null”语义直接搬到只返回 8 个原始 key 的结果上，未同步行数守恒。
- 应遵循规则：内部 gap 应使覆盖它的 feature/pair null，但输出只保留输入 bars 的 unique keys；应断言 `values.len()==8`
  且 `values.null_count()==8`，另用显式 grid/spy 断言 gap 后没有跨洞 pair。
- 通过条件：修正断言并重新绑定 tests/delivery SHA；保留 gap 不跨洞的行为测试。

### P2-1：仍有少量合同矩阵仅由实现源码而非行为测试锁定

当前测试已覆盖主要 §10/§12 节点，但没有直接行为断言：负 volume 的 fail-closed（仅间接依赖 Bar1dSchema）、
`log(volume_t)-log(volume_{t-2})` 的 exact raw-shares 数值与禁止 epsilon、同日 `(close-open)/open` 的精确 oracle、以及
配置节内全部冻结值/类型逐项核对（只核了节顺序、部分身份、trial_delta 和 economic_execution）。这些不足不改变本轮
P1-4 的确定性失败，但在后续修复中应补齐，避免把源码阅读替代为完整测试矩阵证据。

### 复验结论

alias、浮点非退化 fixture、public helper exact1 与主要反例已静态闭合；但 P1-4 仍使当前 exact3 `REVIEW_FAIL`。
本轮复验结论：`P0=0 / P1=1 / P2=1`，实现上限保持 `IMPLEMENTED_PENDING_VALIDATION`。返工后须由未参与实现的上下文
再次复验，并在授权窗口运行定向验证；本 reviewer 不修实现、不运行测试、不提交。
本 reviewer 不修实现、不改 taskbook、不运行验证、不 stage、不 commit，写入本报告后退出。

## FINAL_STATIC_REVIEW_PASS（同一 reviewer，最终返工复验）

### 绑定证据与边界

本轮仅静态读取最新 tests/delivery 与不变 production；未运行 Python、pytest、Ruff、mypy、data、网络、stage 或
commit，也未修改 taskbook、config、共享 helper 或 production。最新 exact3：

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `src/quant/factors/classic_eleventh_batch.py` | 8452 | `6fe8baf1000cb8ffd5b8e58968125f3e6c4069d2e5e76af25940709351f8a4a1` |
| `tests/unit/test_classic_eleventh_batch.py` | 15826 | `17f22016d9268058104276ae1c0d778916c38ee2b77115d70df603ff7f84f6be` |
| `docs/research/deliveries/M2_RESEARCH_R21_Alpha101002量价背离交付报告.md` | 3343 | `58cb657cdfdb1fa6ad3f3d1e1c97087170a15a7ae8ccdab3ff741d33eb1f4b17` |

### P1/P2 闭合

- 内部缺 bar 现在明确断言目标 symbol 只返回 8 个原始 keys 且 8 个均为 null，符合不补 grid 输出合同。
- production 整体 return expression 已先 cast 再 alias；未恢复 alias 绑定风险。
- `_pattern_bars` 提供显式六期非退化 rank 模式，测试用 `pytest.approx` 锁定 exact6 Pearson、负号和 session 8 首值；
  zero-variance 使用独立测试，不再依赖浮点 bit-identical 假设。
- spy 记录真实 long-form 输入并调用真实公共 helper，断言 helper exact1、两个 component 分母独立、缺失不删另一
  component key，且 helper 异常无 private fallback。
- raw helper 输入 oracle 以 `pytest.approx(math.log(3.0))` 检查 raw-share lag2，自然对浮点误差；同日 return 以
  `pytest.approx(0.1)` 检查 `(close-open)/open`；负 volume、zero volume、内部 gap、7/exact8、ties/n=1/n=2、
  permutation、calendar、duplicate、nonfinite、schema、output key/dtype 与零方差均有源码级行为节点。
- config 测试逐项核对 section 顺序、研究/data/universe/factors/coverage/portfolio/admission 字段、alpha 全部冻结值与
  exact type/order、三 fold 日期类型及 trial/economic blocking；未发现与 taskbook 冻结值的静态漂移。

### 最终判定

当前未发现 P0、P1 或 P2；最终独立静态结论为
`REVIEW_READY / FINAL_STATIC_REVIEW_PASS`，即 `P0=0 / P1=0 / P2=0`。
状态上限仍为 `IMPLEMENTED_PENDING_VALIDATION`：该 PASS 不代表 Python/pytest、Linux Gate、真实数据、经济运行或
收益结论通过；应由中央在授权窗口安排定向验证。

## Validation2 后 §15 新独立静态复验

本节由未参与实现及任务书编写的新 reviewer 追加；前述各轮历史及当时 PASS/FAIL 均原样保留，
不以本轮结论回写旧结论。本次结论为 `STATIC_REWORK_REVIEW_FAIL / P0=0 / P1=1 / P2=0`。
唯一未闭合项是测试未完整消费 §15.1 的逐证券中间值矩阵，不是新发现的生产公式错误。

### 输入身份、范围与证据强度

HEAD fresh 为 `ab78a059044d49e2d8f3e94dd5b1087f55a9f86e`；同一冻结 worktree，actual exact6
均 untracked、cached0。当前只读取合同、源码、配置、报告和 Git/文件身份；仅追加本 review。

| 输入 | bytes | SHA256 |
| --- | ---: | --- |
| taskbook | 39375 | bf2730bf1b39c74f56af5b500971d55d6245a7374b641da94a9fb4003f014d65 |
| production | 8592 | 41a2784cb8c1a3ef088a6d304a5796ee4e392cefbdf1b178630f70624d687c55 |
| test | 19448 | beac4b98369f5c9b521abbd3e7ab7a25daae2af45e660cf6af96650d3384a718 |
| config | 2774 | 0ca63e41fa77bb36c72eaedc2b1c713169bdf9c02add6e2387aec749b574cc5b |
| delivery | 3990 | fff9353bb6170086318fdc52038b6e174f013ed65422a4f5d4e47293d635221e |
| 本次追加前 review | 15918 | b05ba94d9663cd39dfb92019909010e5ea7bcda17e9466366439d3f55fc1ff2b |

Validation2 的 `3 failed, 9 passed`、chunk `9ee9b5`、exit1 和 Ruff/mypy UNRUN 来自冻结任务书
与中央交接，并非本 reviewer 重新执行或重新捕获的原生输出。本次 Python、pytest、Ruff、mypy、
data/network、经济计算、trial、root 创建、cleanup、stage/commit 均为0；新产品验证仍未运行。

### 已静态闭合的修正

1. **数学与价格 fixture**：`_pattern_bars` 的共同 open=128、close=128+整数差使收益为精确
   binary 分数；同日名义 ties 不再依赖不同 open 的十进制浮点重建。成交量使用显式指数序列，
   其三种 log-delta 次序间隔为1；数值非精确性不能作为省略真实 rank 断言的理由。
   手工复核 A/C 的六期 centered cross=-3/4、volume SS=1、return SS=13/12，故负 Pearson 为
   `3*sqrt(3)/(2*sqrt(13))`；B 两序列一致且非恒定，故为-1。源码 expected 来自该公式，
   没有把 V2 观测浮点值回填为 expected。
2. **独立 ±1**：`_relation_bars(reverse=False/True)` 每日 return 次序分别等于/反于 volume 次序；
   三只证券的六期 rank 非恒定，分别期望-1/+1，未混用原 pattern 的相关值。
3. **calendar**：合法末尾超集与原 keys/output 相等；移除有 bar 日期、逆序及重复日期分别拒绝。
   production 仍只要求 bars 日期属于 sessions，没有强制两集合相等。
4. **lag1 presence**：新增 `_bar_present.shift(1).over("symbol")` 并在 volume feature 条件中检查等于1。
   现有 gap 节点捕获传入真实 rank 的 frame，在缺 g=session[3] 后的 t=session[4]，明确断言
   volume_change 为 null；不是只检查最终 rolling null。无gap处该条件恒真，其余算法未变。
   只读逆向移除这两条新增源码行，得到8452 bytes及
   `6fe8baf1000cb8ffd5b8e58968125f3e6c4069d2e5e76af25940709351f8a4a1`，与返工前 production 精确一致。
   未改公共 rank、config、公式、窗口、方向、错误顺序或输出 keys。

### P1-§15-MATRIX：只核 A 的输出 rank，不满足冻结的全部中间值合同

- **现象**：`test_exact6_pearson_negative_and_first_value_is_session_eight`（当前84–105行）的 spy
  仅 `captured.append(result)`，没有保存此 pattern 的输入 frame；98–99行仅核 A 的两个后六期 rank。
  B/C 只在最后因子值的 `pytest.approx` 中出现，没有按 date/symbol 精确断言其两组件 rank。
  其他 raw-value spy 节点采用不同 fixture，不能替代 §15.1 指定 pattern 的输入/输出闭包。
- **根因/责任域**：tests-only；实现仅部分转录了任务书的 A/B/C 三行矩阵。当前手工数学可确认
  预期正确，但源码阅读与最终相关值不等于完整中间行为断言。
- **应遵循规则**：§15.1 已要求真实公共 rank 薄 spy 同时捕获输入和输出，并按 date/symbol 核
  三证券、两组件、后六期；不得改数学公式、生产 rank 或预期矩阵来缩小这一合同。
- **最小复现/独立对抗**：Pearson 对每条序列的正仿射变换不变。若错误实现仅把 B 的 u/r 同时
  改成 `0.25 + 0.5*x`，最终 B 仍为-1，A 的两条 rank 检查也不受影响；仅终值断言不足以排除
  错误归一化或成员映射。这是未执行的静态反例，不声称当前生产实际实施了该变换。
- **最小新增测试**：沿现有薄 spy 保存同一次真实调用的 frame/result，断言 call count=1；按显式
  `sessions[2:8]` 与 A/B/C、component keys 取行，核每 key 恰好一次及全部冻结 rank 列表。
  输入 intraday_return 应对应明确整数差/128；volume_change 按独立 d_volume 序列和适合 log
  舍入的数值比较检查，不从生产输出反推 expected。rank 的0、0.25、0.5、0.75、1本身用精确相等。
- **通过条件/最小写路径**：仅原 test 文件及 delivery 追加修正说明；保留既有±1、exact8、gap、
  calendar 和数学终值测试。production/config/helper/taskbook 不需因本项修改。独立静态复验闭合后，
  再按中央新授权运行 Windows 验证；本 reviewer 不修代码、不自行运行。

### 另一独立边界挑战：lag1 零成交量不等于缺 bar

令 t-2 与 t 的 volume 分别为10、30，而 t-1 bar 存在且 volume=0，三日 open/close 合法。
§15.3 要求 t 的 volume_change 为 log(30)-log(10)，不得因 lag1 volume=0 额外变 null。
静态追踪当前 guard：lag1 只读 `_bar_present_lag1 == 1`，正值检查仅消费 current/lag2，因此满足该边界。
此例不同于新增 missing-lag1 节点，是本 reviewer 的未执行静态对抗；不把它描述为已增加或运行的测试。

### 本轮最终裁定

`STATIC_REWORK_REVIEW_FAIL / P0=0 / P1=1 / P2=0 / IMPLEMENTED_PENDING_VALIDATION / TRIAL0`。
阻断项仅为 §15.1 中间测试证据未完整落地。V2 历史失败不抹除，新的 static 修正不冒充运行 PASS，
经济有效性仍 UNASSESSED。以上追加之外未改历史；写后由经理 fresh 核最终 review identity。

## §15.1 MATRIX 同一独立 reviewer 定向复验 PASS

原实现者已退出。本 reviewer 按中央准入仅复验上一节唯一 P1 并追加本节，不修改前22229 bytes历史。
fresh taskbook、production、config身份与上一轮逐字相同；更新输入为：

| 输入 | bytes | SHA256 |
| --- | ---: | --- |
| test | 21597 | 182ac5b1d30ece4a796b4b96230a48e34b38f59fb61b210d280d6785dbdc6ba6 |
| delivery | 4713 | 4588dfb03a93212ed675843176ea795eeb10a5e160f2172681df0ca5b2ebbd3c |
| 追加前 review | 22229 | 2f155f155bee9ee2492a8fe69649a8fa3986b00c464b9aceca0e60ddec0af94a |

### 唯一 P1 的逐项闭合

- 同一薄 spy 先记录 frame，再调用 captured original public helper，记录其 result 并原样返回；
  captured_inputs/captured_outputs 长度均断言1，没有 fake rank 或额外生产调用。
- 输入48行、三key无重复、date/component/symbol集合分别精确为8/2/3个值，故覆盖完整笛卡尔积；
  后六期另断言36行。循环逐证券和组件按显式 `sessions[2:8]` 过滤并按日期排序，比较六个独立预期值；
  输出经真实公共helper的保key/唯一键校验，再逐A/B/C、组件精确比较六期rank，不以终值代替。
- intraday输入采用 exact equality，对应共同128分母的整数差；volume输入采用独立d_volume数列的
  `pytest.approx`，仅容纳自然log舍入。rank的0、0.25、0.5、0.75、1全部exact equality。
  该拆分遵守冻结的精确binary与log数值边界，没有把两个输入都放宽为approx。
- A/B/C全部rank矩阵与§15.1一致，手算的 `3*sqrt(3)/(2*sqrt(13)),-1,3*sqrt(3)/(2*sqrt(13))`
  及前七期null、第八期首值仍保留；独立±1、calendar和lag1反例未被本项替代。
- 上轮独立正仿射反例现在被直接击穿：B的volume原序列含1与0，变换后为0.75与0.25，必然不等于
  新循环中的精确expected；即使最终相关仍-1，也不能通过该中间断言。这是源码级逻辑证明，未运行mutation。
- delivery追加准确说明全矩阵及exact/approx分工，没有把V2的3failed9passed/Ruff-mypyUNRUN改写为已通过。

### 最终结论与执行边界

`STATIC_REWORK_REVIEW_PASS / P0=0 / P1=0 / P2=0`，上一节 P1-§15-MATRIX 已闭合；历史FAIL仍有效保留。
production/config/taskbook无需为此继续修改。本轮零Python、pytest、Ruff、mypy、data/network、经济trial、
root创建、cleanup、stage/commit；实际产品验证仍待中央另授新identity/Temp的direct-native窗口。
状态上限 `IMPLEMENTED_PENDING_VALIDATION / ECONOMIC_UNASSESSED / TRIAL0`，不宣称Windows或Linux Gate通过。

## Validation3–5 evidence-only 独立收口

本节按中央 turn `01a07ace-4ae8-72e2-be1a-321a98ccf206` 准入，由同一独立 reviewer 仅在EOF追加。
前24879 bytes历史保留，不改静态审查的执行时态。结论：`EVIDENCE_REVIEW_PASS / P0=0 / P1=0 / P2=0`。
该 PASS 只接受如下有偏差的产品阶段与证据记录，不追认所有执行控制合同均合规。

### 独立读取的 authority 与可见性

本 reviewer 独立通过 read_thread 读取中央 V3 turn `01a07ac6-74b8-79a2-8d5a-367706058dec`、
V4 turn `01a07ac7-dd70-70d0-8cfc-e580df844a75`、V5 turn `01a07ac9-c26a-7241-8bb6-8dda34e7a4ce`
的完成记录、阶段总结和收件；另读取当前 taskbook §16、delivery及文件/Git身份。
本次工具所返回的是中央 agentMessage 与消息回执，没有显示产品命令的完整原始工具输出或完整运行argv；
以下 chunk/session、native exit、运行前资源/cache基线与归因均按中央执行者明确记录和裁定引用，
不声称本 reviewer 重新取得原始stdout/stderr字节、重跑产品或生成日志SHA。

| 阶段 | 中央可见记录 | 独立裁判 |
| --- | --- | --- |
| V3 | chunk32bc00，outer exit1，foreach token错误；Python0/T3 absent | 产品未执行，不归因因子，不冒充产品FAIL |
| V4 unit | a67398，14 passed / 196 warnings / 2.88s，exit0 | 由V5中央明确接受为同一冻结代码的有效unit证据，不重复unit |
| V4 Ruff | All checks passed文本；1f9cb6 outer exit1，状态输出/exit词法失败 | 没有可靠阶段exit闭包，不能用绿色文本作为完整验证PASS；mypy当时UNRUN |
| V5 Ruff | aecbea，All checks passed，可靠exit0 | 工具阶段有效，但argv偏差单独保留 |
| V5 mypy | session47575 / be6631，Success: no issues found in 1 source file，exit0 | 工具阶段有效，不推导Linux或经济准入 |
| V5 scope/resource | 初次只读控制表达式失败，随后无循环只读核完成；exact6/cached0，Normal/0xFFF/Python0 | 保留首次失败，不称第一次scope已通过；资源值是中央执行后记录 |

### 实际命令偏差、cache与保留边界

taskbook §16、delivery和中央V5裁定一致：实际Ruff七项argv顺序为
`-m, ruff, check, <production>, <test>, --config, <pyproject>`，绝无独立 `--no-cache`。
因此原生exit0不能证明§14 exact command合规。中央根据其pre-V5 root-cache-empty记录，明确把
新增root `.ruff_cache` 归因于V5；本 reviewer没有独立历史pre快照，不把当前存在性反向包装成历史证明。
future执行必须显式核该literal flag；本轮不修改argv历史、不重跑、不删除残留。

本 reviewer fresh只读核：`.ruff_cache`、T2/T4/T5均存在、directory/non-reparse、git check-ignore exit0；
T3不存在。以上T编号与taskbook §14/§16 exact路径相同。T5的19files/2dirs/39,440,831bytes为中央盘点值，
本轮未重新枚举全部临时文件；只证明这些保留root当前仍在，不伪称当前全内容manifest已重算。
cache/Temp必须排除提交，没有cleanup、退休或经济执行授权。

### 前后身份及历史不混用

执行前taskbook39375/bf2730bf1b39c74f56af5b500971d55d6245a7374b641da94a9fb4003f014d65，
delivery4713/4588dfb03a93212ed675843176ea795eeb10a5e160f2172681df0ca5b2ebbd3c，
review24879/2838f84fbdd419dd8a535cb33fbac6907bb6c69fcffc96c5872f93f7d6676a44。
当前证据写回后taskbook44291/424556e3df7d879a92d368838440f97da35692ff55f846b15b5900edfe850ad8，
delivery6631/bc74526d3d5922dc8c176fc243d1516d010e0743807f9062175d1704f86c3997。
两文件原39375/4713-byte前缀由本 reviewer分别重算SHA，逐字等于执行前值。
production8592/41a2784cb8c1a3ef088a6d304a5796ee4e392cefbdf1b178630f70624d687c55、
test21597/182ac5b1d30ece4a796b4b96230a48e34b38f59fb61b210d280d6785dbdc6ba6、
config2774/0ca63e41fa77bb36c72eaedc2b1c713169bdf9c02add6e2387aec749b574cc5b均保持冻结identity。

fresh HEAD/branch仍ab78a059044d49e2d8f3e94dd5b1087f55a9f86e/原branch，actual exact6全untracked，cached0。
普通diff native exit0仅为VACUOUS_FOR_EXACT6；本 reviewer另对六文件做strict UTF8/noBOM/CR0/NUL0/TW0/
singleEOF检查，均通过。本节追加不改变其余五文件；最终reviewSHA由写后检查返回，不写自指值。

### 独立对抗裁判

1. 若把V4 `All checks passed!` 文本替代缺失阶段exit，再把V5写成无偏差development validated，
   会同时遗漏outer exit1与`--no-cache`缺项；应REVIEW_FAIL。本次两文档明确分别记录，未犯该错误。
2. 若把当前44291-byte任务书SHA当V4/V5执行输入，就与冻结39375-byte身份冲突；
   本次原前缀SHA和新增§16分离，拒绝该混同，不把文档补记伪造成历史执行前状态。
3. 若以当前cache存在替换中央基线来源，或把另一任务cache归因未知套到R21，也不成立；
   本次仅引用R21中央明确归因，并诚实标明本 reviewer未取得历史raw pre快照。

### 最终状态上限

`R21_WINDOWS_PRODUCT_STAGES_PASS / CONTROL_CONTRACT_DEVIATION_RECORDED / CACHE_RETAINED / ECONOMIC_UNASSESSED / TRIAL0`。
可按中央裁定申请exact6 safe commit，但不是无偏差的WINDOWS_DEVELOPMENT_VALIDATED，也不是实际策略有效。
未关闭Linux Gate，不授权新trial、策略run、PAPER/LIVE。本review轮零Python/pytest/Ruff/mypy、真实data、
资源设置、root创建、cleanup、stage/commit；仅追加本报告后退出。
