# M3 G1 P0 返工任务书（2026-07-26 冻结）

> 依据：[`20260726_M3_G1_Windows轨Codex主验不通过与P0返工裁定.md`](20260726_M3_G1_Windows轨Codex主验不通过与P0返工裁定.md)；  
> B2C §9.2：[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](M3_G1_P3_B2C执行事实外部闭环任务单.md)。  
> **不宣称** Codex 终验 / Linux Gate。旧 release `3c9bda84…` 仅诊断，禁止作 G2A 输入。

## 会话白名单（互斥）

| 角色 | 模型 | 可写 |
|---|---|---|
| 实现 | 全新 `cursor-grok-4.5-high` | 生产代码/测试 + **唯一**实现交付报告 |
| 独立初验 | 另一全新 `cursor-grok-4.5-high`（未参与实现） | **仅**自己的初验报告；生产/测试只读 |
| 协调 | 本会话 | 任务书、进度、合流后状态文档；**不得**直接修 P0 后跳过初验 |

### 实现可写路径

- `src/quant/data/m3_execution_facts.py`
- `src/quant/data/m3_g1_candidate.py`
- `src/quant/data/m3_release.py`（仅版本/合同闭合所需；Windows 路径已存在则补测试与报告）
- 若版本贯穿需要：`src/quant/research/m3/g1_planning.py`、相关 config schema/测试
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_g1_release.py`（Windows publish 对抗）
- 唯一交付报告：`docs/framework/agent/M3_G1_P0返工_A_B_C实现交付报告.md`

### 独立初验可写路径

- 唯一：`docs/framework/agent/M3_G1_P0返工_A_B_C独立初验报告.md`

## 返工 A — reconciliation fail-closed（B2C §9.2）

1. 无事件：仅 `abs(actual_factor_ratio-1)<=rtol` → `NO_EVENT_STABLE_FACTOR`；否则 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。
2. 有事件：缺前收 / 分母非法 / actual|declared|market ratio≤1 / PARTIAL 或缺 daily 无 FULL_DAY / 两路径均超 rtol → **失败**，不得回退 `event_count=0` 或伪装 `NO_EVENT_STABLE_FACTOR`。
3. 禁止把配股/增发等未知资本事件装成稳定无事件；正式数据因此失败则保留首败证据并停止扩大实现。
4. 恢复/新增测试反例：无事件 1.5 jump 拒绝；PARTIAL 缺 daily 拒绝；event 证明超差拒绝。

## 返工 B — membership/eligible 权威重建

1. **废止** audit 以 `count∈[1,300]` 为充分条件（早期合同修订对此点被本裁定覆盖）。
2. audit 调用 `quant.data.index_membership.build_observed_membership`，入参来自 candidate 自带 observations/calendars/instruments/universe/signal_start/signal_end，`expected_constituent_count=300`。
3. 重建的 membership 与 eligible_keys 必须与 candidate **逐字段相等** + 内容 digest；不复制第二套算法。
4. 真实 299 仅当权威 builder 因 lifecycle 精确产生时通过。
5. 对抗测试：happy candidate 的 `eligible_keys` 重绑 `head(1)`（即使同步 table digest / required digest / primary_candidate_key）→ audit 必须失败；单删一个非生命周期成员 → 必须失败。

## 返工 C — 版本与 Windows PUBLISH 职责闭包

1. 审计并升级仍含新语义的：`G1_PRICE_LIMIT_METHOD_VERSION`、`G1_CORPORATE_ACTION_SELECTION_VERSION`、`G1_CORPORATE_ACTION_RECONCILIATION_VERSION`；贯穿 config/planning/candidate/manifest/测试；**不得**为保 key 保留错误 v1。
2. Windows PUBLISH（MoveFileExW / O_BINARY / dir-fsync）：补齐实现交付叙述；独立初验覆盖 no-clobber、并发、二进制 hash、reparse/symlink、Linux 路径未改、不冒充 ext4 Gate。

## 实现者自验（最低）

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_release.py -q --tb=line
定向 ruff / mypy；git diff --check（仅己方改动）
```

禁止：reset/checkout、批量换行、删旧 release、改 raw/receipt、输出 token、重复五身份 510300、自行宣布 Gate/Codex 终验、启动 G2A。

## 协调后续（实现+初验均通过后）

零网络 status →（key 变则隔离旧 baostock journal）有界 REFERENCE → PREPARE → Windows PUBLISH → 磁盘 `verify_g1_release` → 更新 CODEX_HANDOFF / M3 总览 / 路线图 Windows 轨事实（仍不宣称 Linux Gate）→ 压缩总报告交用户。
