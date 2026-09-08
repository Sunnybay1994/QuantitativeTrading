# M3 G7D-F0 R4：benchmark 510300 SSOT 独立复验报告

日期：2026-08-09  
角色：未参与 R4 实现的全新独立初验 Agent  
结论：**PASS；R4 已关闭 formal F0 benchmark selector 的 SSOT 冲突，可提交主 Agent 最终验收。本报告不宣布主验、G7E 恢复或 M3 Gate PASS。**

## 1. 审查范围与只读边界

完整核对了 F0 任务单第 13 节、`docs/framework/M3实施与Agent交接.md`、
`configs/research/m3_qlib_example.toml`、R4 交付报告，以及当前
`src/quant/backtest/a_share_execution.py` 和 F0/G7C/F1/F2 邻接测试。生产代码和实现者测试保持只读；本轮
唯一写入为本报告。未联网、未 add、未 commit，WSL 工作树仍位于 `/mnt/f`/DrvFS。

## 2. 契约映射与结论

1. **selector 唯一来源与时序：PASS。** F0 在 `verify_g1_release` 与
   `verify_backtest_plan_artifact` fresh 返回并逐字段比对后，才读取
   `fresh_context.config.section("data")["benchmark"]`；仅接受 exact `str` 且 exact `510300.SH`。事实文件读取
   与八表 selector 均发生在 fresh 之后；没有新增 caller selector/path、裸 TOML 读取或 F0 平行常量。
2. **旧基准和混表关闭：PASS。** 独立探针证明仅含 `H00300.CSI` 的 benchmark frame 被拒；old/new mixed
   frame 只选择 `510300.SH x execution_dates`。选中 510300、旧 H00300 及对 510300 close 单点漂移后的
   content digest 前缀分别为 `6c591f917305`、`dc12751f7466`、`eeffcb809224`，三者不同；正式
   `artifact_digests/content_sha256`、capability whole hash 与 `input_market_facts_sha256` 的既有闭包因此自然随
   selected content 变化，不能复用旧 capability/token/hash。
3. **G7B config 漂移先失败：PASS。** formal G7B 的 cost/config 低层漂移反例通过；F0 独立定向同时证明
   hostile G7B fresh 在 config/frame 访问前失败。config section 自身 hostile exception 统一折叠为
   `M3_A_SHARE_MARKET_FACTS_INVALID`，`__cause__`/`__context__` 为空，不泄露 hostile token/path。同步修改低层
   config document/whole hash 不会绕过 G7B fresh；F0 不自行读取未验真文档。
4. **F1 date guard 与 capability 边界：PASS。** public F1 对 fake、development 类型、subclass 与裸 frame
   均在任何 property 访问前按 exact runtime type 拒绝。合法 F0 `510300.SH` capability 可贯穿 F1 open-state/
   quantity rule，并由 F2 session transition 消费；F1 date guard 只检查已自验 capability 的 benchmark frame
   对请求 date 恰一行，不再维护第二份 benchmark 代码判断。F2 仍只接受同一 exact capability。
5. **R3 capability 与 reload 隔离：PASS。** reload 后旧 capability 在 fresh subprocess 中拒绝；八表内容、
   provenance、whole hash、process-local attestation 的既有防伪覆盖仍在，R4 未扩大 mint/factory surface。
6. **生产残留审计：PASS（按语义限定）。** `src/quant/backtest/a_share_execution.py` 与正式配置中无
   `H00300.CSI`。全 `src` 扫描另有两处既有字符串：`g1_planning.py` 用其作为复用旧请求构造器的临时参数并
   立即剔除 `index_daily`，最终正式 G1 ETF closure 仍为 510300；`readiness.py` 的 `_LEGACY_BENCHMARK` 专用于
   识别和拒绝旧基准。两者不进入 F0 selector/capability，不构成正式 benchmark 混用；因此不能把本项表述成
   “整个仓库零 H00300 字符串”。历史报告中的字符串未计入 production 审计。
7. **范围控制：PASS。** 本轮公共 API 签名未变化；`backtest/__init__.py`、config、G1/G7B/G7C、正式
   artifact/journal 未因 R4 修改。源码改变集中于 F0 selector 与 F1 遗留 date guard，符合第 13 节白名单。

## 3. 独立新增对抗证据

- 仅旧 H00300 frame + formal 510300 selector：拒绝。
- old/new mixed frame：只返回 510300；旧、合法、单点内容漂移三者 digest 均不同。
- G7B config payload 低层漂移与 hostile fresh：在 F0 config/frame 使用前拒绝；hostile section/cause/context
  脱敏。
- fake、development 类型、subclass：F1/F2 在 frame property 访问前拒绝。
- 合法 510300 F0 capability：F1 正向 projection/rule 与 F2 exact-once session transition 均成功。
- reload → development facts → formal G7B → development G7E 固定顺序：双平台各 26 项通过，未发现类型或
  capability 污染。

## 4. 验证结果

### Windows 原生 Miniforge

- F0 + G7C + F1 + F2 当前正式邻接：**74 passed**，343.65s。
- 独立 G7B config drift、F0 fresh/脱敏、F1/F2 exact-type/贯穿节点：**6 passed**，35.45s。
- 固定顺序回归：**26 passed**，176.59s。
- 独立 old/mixed/content digest 探针：**PASS**。
- Ruff：**PASS**；mypy `--no-incremental`：**PASS**；cold import、公共签名、factory removal、
  heavy-dependency isolation：**PASS**；限定 `git diff --check`：**PASS**。

### WSL Miniforge base

- F0 + G7C + F1 + F2 当前正式邻接：**74 passed**，262.27s。
- 固定顺序回归：**26 passed**，80.17s。
- Ruff：**PASS**；mypy `--no-incremental`：**PASS**；cold import、公共签名、factory removal、
  heavy-dependency isolation：**PASS**。

实现交付报告记录的邻接数为 76；独立复验按后续 F2 测试演进后的当前收集结果执行为 74，两平台收集与执行
一致，均无 skip/失败。本轮曾有一次定向命令引用不存在的旧测试节点名，pytest 在 collection 阶段退出、未执行
测试；更正为当前节点名后上述 6 项通过，不将该操作错误计为产品失败。

两平台 warnings 仅为既有 Pandera Polars deprecation 与工作树 `.pytest_cache` 权限告警。WSL 结果只证明
`/mnt/f` DrvFS 兼容，不证明 Linux/ext4 Gate。

## 5. 剩余边界

- 本报告只判定 G7D-F0 R4 工程返工通过独立初验；不证明真实 G1 数据、真实账户、完整 work、Linux/ext4、
  G7E/G7F 或 M3 Gate。
- `g1_planning.py` 的临时 legacy 参数属于既有实现债务，当前会明确过滤对应 `index_daily`，不阻断 R4；若
  后续重构该构造器，应消除这一内部临时参数，但不得借 R4 越界修改 G1。
- G7E 仍须等待主 Agent 最终验收明确 PASS 后再恢复冻结/实现流程。
