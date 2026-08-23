# M3 G1 R1C-B INDEX 身份合同返工独立复验 Prompt

角色：全新外部独立复验 Agent（生产代码、测试、配置和 data 全部只读）  
模型：`cursor-grok-4.5-high`  
前置：身份合同返工实现 Agent 已完全退出并提交交付报告

## 1. 唯一允许写入

- `docs/framework/agent/M3_G1_R1C-B_INDEX身份合同返工独立复验报告.md`

禁止修改、格式化或“顺手修复”任何生产代码、测试、配置、真实 raw/journal。禁止网络，禁止调用 `index`、
`history`、`reference`、`prepare`、`publish`、`run-all`。禁止读取或输出 token。

## 2. 先读合同和证据

完整阅读：

1. `AGENTS.md`
2. `docs/framework/agent/M3_G1_R1C-B_INDEX身份合同返工任务单.md`
3. `docs/framework/agent/M3_G1_R1C-B_INDEX交付报告.md`
4. `docs/framework/agent/M3_G1_R1C-B_INDEX独立复验报告.md`
5. `docs/framework/agent/M3_G1_R1C-B_INDEX身份合同返工交付报告.md`

不能只复述报告或以测试绿色代替合同核对。

## 3. 必验项

### 3.1 纯合同

- 合法全量 instrument 超集中加入无关 ETF 后，observations/membership/eligible 三表及三个 digest 与只含所需
  STOCK 的输入完全一致；无关行不得进入 mapping 或 identity。
- observation 实际引用的 ETF、非 CNY、错误 market、缺失 instrument 仍稳定失败。
- 299/301 **observation** 仍失败；此次修订只允许生命周期裁剪后的 eligible 少于 300。
- 月中退市后该 symbol 当日及之后不得进入 eligible，下一 observation 前 299 合法；不得补造替补证券。
- 每个 signal open session eligible 非空、唯一、排序确定且 `count <= 300`；空 session、>300、重复/闭市/窗口外
  键继续 fail closed。
- public verifier 必须用同一修订合同从原输入重建；自洽伪造 hash、payload 篡改和异常 cause/path 均拒绝。

新增至少一个实现者没有使用的反例，优先：多个无关 ETF/INDEX 混合且输入行序变化、同 observation 所需 symbol
出现 duplicate/非 STOCK、连续两个成员在同月退市导致 298、delist_date 恰为 observation/activation/session 边界。

### 3.2 真实 evidence（全程零网络）

用新进程运行一次：

```bash
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

必须验证：

- `outcome=INCOMPLETE`、exit 0、`completed_stages` 精确 `[INDEX]`；
- INDEX plan/receipt/raw request identity 集合精确相等且为 127，月份仍为 2015-12…2026-06；
- raw/journal 没有被返工重写或扩展到 HISTORY 端点；
- `history_symbols=S`、`history_requests=4*S+131` 数学闭合；CLI 在 candidate 前若把
  `reference_requests` 报为 0，应明确区分“当前 workflow count”与未来理论 BaoStock 请求 `S`；
- eligible 计数分布能解释真实 46 个 299 日，并核对三个已知退市空窗；若真实数字变化，必须从当前证据说明，
  不得硬编码迁就报告；
- 无 HISTORY/REFERENCE/PREPARE/candidate/release/PUBLISH 完成证据；
- 只读凭据扫描命中 0，报告不得输出疑似 secret 内容。

### 3.3 身份与版本

- `membership_method_version` 保持 `tushare_monthly_observed_next_session_close_v1`，因为可知时点/激活方法未变；
- G1 source-tree/code identity 已因生产代码变化而改变；derived membership/eligible identity 来自当前 payload；
- 127 个 request ID 仍只由冻结 endpoint/params 闭合，可安全复用，不能被当前 code hash 伪造为新网络证据。

## 4. 高效验证

只运行实现者新增 test node 和至多 2–4 个独立对抗 test node；禁止重复整份
`test_m3_g1_workflow.py`/`test_m3_run_g1.py`，禁止全量 pytest/Ruff/mypy。若静态审查足以证明未改相关模块，不重复
实现者已经完成的长回归。

## 5. 裁定

全部通过才写“独立复验通过，可交主 Agent 终验”。任一 P0/P1 失败则写清：现象、根因、被破坏不变量、最小
复现、新增测试与返工通过条件，并判定不通过。不得宣称 R1C-B、G1、M3 或 Gate 完成。
