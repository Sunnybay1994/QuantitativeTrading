# M1 HK-HISTORY R1：港股 Close 有界包络返工独立初验报告

日期：2026-08-15（Asia/Shanghai）  
角色：外部独立初验 Agent（全新会话；未参与实现）  
模型：`cursor-grok-4.6-high`  
合同：[`M1_HK-HISTORY-R1_港股Close有界包络返工任务单.md`](M1_HK-HISTORY-R1_港股Close有界包络返工任务单.md)  
交付：[`M1_HK-HISTORY-R1_港股Close有界包络返工交付报告.md`](M1_HK-HISTORY-R1_港股Close有界包络返工交付报告.md)  
取证：[`M1_01065_20260515_OHLC异常Cursor只读取证报告.md`](M1_01065_20260515_OHLC异常Cursor只读取证报告.md)

**初验结论：PASS**（仅解锁主 Agent 终验；**不宣布** M1 / HK60 Gate 通过）

---

## 独立性与范围

- 未参与实现，使用独立上下文：是
- 生产代码、实现者测试、任务单、交付报告：只读
- 唯一持久写入：本报告
- 禁止项已遵守：未读 `data/`、`artifacts/`、ignored 配置、token/账号；未联网；未 `git add` / `commit` / `push`
- 临时对抗探针：`_tmp_hk_close_envelope_adversarial_r1.py`（仓库根目录，已删除）

检查对象：

| 对象 | 方式 |
| --- | --- |
| `src/quant/data/mappers.py` `TushareBarMapper` | 对照冻结规则阅读实现；`git diff` 仅该文件 +47/−3 |
| `tests/unit/test_tushare_connector.py` | 对照必测反例；`git diff` +31/−1 |
| `README.md` mapper 行为段 | 对照合同语义；`git diff` 仅该段 8 行 |
| `src/quant/domain/schemas.py` `Bar1dSchema.ohlc_valid` | 确认工作区未改（不在 diff 中） |
| 实现者交付报告 | 逐项映射，不复述为事实 |

---

## 标准—证据—结论

| 冻结规则 / 必测反例 | 独立证据 | 结论 |
| --- | --- | --- |
| 仅改 HK canonical；A 股/非 HK、`Bar1dSchema.ohlc_valid` 不变 | diff 只动 `TushareBarMapper` 的 `when` 链；Schema 文件无 diff；对抗：SH `4.37/4.38/4.35/4.39` 与 SZ close&lt;low **不**扩展且 Schema 拒绝 | 通过 |
| raw `open/high/low/close` 不改写 | `raw.select(...)` 生成新 frame；01065 四值 + `vol/amount/_market` 映射前后 `to_list()` 一致；exact 5% / just-over 批次同样 snapshot 相等 | 通过 |
| 有限为正且 `raw_high >= raw_low` 才允许 close 包络 | `ohlc_finite_positive` 与 `high_price >= low_price` 合取进 `hk_close_only_mismatch`；`high&lt;low`、零/负/NaN/±Inf close 仍 Schema 拒绝 | 通过 |
| 既有 HK open-only 保持（close 须在原区间） | `hk_open_only_mismatch` 条件未放宽；既有上/下越界测试仍在且本轮通过 | 通过 |
| close-only：open 已在区间、一侧越界、分母=最近正边界、≤5%；`high=max(raw_high,raw_close)`、`low=min(raw_low,raw_close)` | 01065 → clean high=`4.39`；exact 5% 上沿 `100→105`、下沿 `50→47.5` 扩展；just-over `105.01`/`47.49` 不扩展；分母陷阱 `(50-47)/50=6%` 拒绝（若误用 high 会放行） | 通过 |
| open+close 同时越界继续拒绝 | 实现者：两上沿；对抗：开低+收高、开低+收下、开高+收下，canonical 均不扩展，Schema 拒绝 | 通过 |
| 5% 只是脏数据上限，非价位表/CAS 证明 | mapper docstring 与 README 均写明；代码无 HKEX 价位表 | 通过 |
| 范围：不改 Schema/连接器/raw/journal/其他模块 | `git diff --stat` 仅 README + mappers.py + `test_tushare_connector.py` | 通过 |

R0「港股 close 越界一律硬失败」已按任务单废止：旧元组 `HK 3.00/3.06/2.92/3.08` 现为 close-only 正向（对抗探针确认 Schema 通过）。实现者测试已改为「小偏离通过 / 大偏离拒绝」，与合同一致。

---

## 新增对抗性反例（实现者未使用）

实现者覆盖：01065 小上沿、小幅 close&lt;low、SZ 开/收越界、远超 5%（`close=10`）、两上沿同时越界、close 上的 0/负/NaN/±Inf、`high&lt;low`。  
下列全部为初验临时探针，**未写入** `tests/unit/test_tushare_connector.py`。

| # | 反例（实现者未用） | 期望 | 结果 |
| --- | --- | --- | --- |
| 1 | exact 5% 上沿：HK `75/100/50/105`，分母=high | 扩展 high=`105`，Schema 通过 | 通过 |
| 2 | just-over 5% 上沿：HK `75/100/50/105.01` | 不扩展，Schema 拒绝 | 通过 |
| 3 | exact 5% 下沿：HK `75/100/50/47.5`，分母=low | 扩展 low=`47.5`，Schema 通过 | 通过 |
| 4 | just-over 5% 下沿：HK `75/100/50/47.49` | 不扩展，Schema 拒绝 | 通过 |
| 5 | 分母陷阱：HK `75/100/50/47`（相对 low=6%，相对 high=3%） | 必须拒绝 | 通过 |
| 6 | R0 旧硬失败元组现应放行：`3.00/3.06/2.92/3.08` | close-only 通过 | 通过 |
| 7 | 同时越界（开低+收高，均 &lt;5%）：`89/100/90/104` | 不扩展，拒绝 | 通过 |
| 8 | 同时越界（开低+收下 / 开高+收下） | 不扩展，拒绝 | 通过 |
| 9 | A 股 SH 复用 01065 四值 | 不扩展，拒绝 | 通过 |
| 10 | A 股 SZ close&lt;low（实现者只测了 SZ close&gt;high） | 不扩展，拒绝 | 通过 |
| 11 | NaN/Inf/负/零作用于 open/high/low/close（非仅 close） | Schema 拒绝；raw 不变 | 通过（见残余） |
| 12 | 01065 全字段 raw 保持 + mixed 三行批次（HK 包络 / SH 同数 / HK 同时越界） | 行内隔离；raw 不变 | 通过 |
| 13 | close 恰等于 high：不视为「一侧之外」 | 不扩展，Schema 通过 | 通过 |

残余观察（**不构成本轮 FAIL**，白名单禁止改 Schema）：

- 现象：HK `open=3.00, high=+inf, low=2.92, close=3.08` 经 mapper 后 `Bar1dSchema.validate` **通过**。
- 根因：`Bar1dSchema` 字段 `gt=0` 接受 `+inf`；`close <= +inf` 使既有 open-only 条件为真，canonical high 仍为 `+inf`。即使不走任何包络，`ohlc_valid` 对 `+inf` high 亦成立。
- 与本任务关系：close-only 路径已要求 `is_finite()`；`+inf` **close** 仍 fail closed。`+inf` **high** 是 Schema 既有缺口，修复需改 `Bar1dSchema`（本任务禁止）或改变 open-only（任务要求保持）。主验可记为后续 Schema 有限性议题，不阻塞本 close 包络合同。

---

## 问题

无阻塞返工项。

（PASS 不填写「现象—根因—规则—最小复现—新增测试—通过条件」返工块。）

---

## 验证

环境：Windows `D:\Miniforge3\python.exe`（开发反馈环，**不替代** WSL base Gate）。未联网、未请求 Tushare、未读 token。

| 命令或检查 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/unit/test_tushare_connector.py _tmp_hk_close_envelope_adversarial_r1.py -q --tb=line` | 通过 | `51 passed`（实现者 35 + 对抗 16），3.52s |
| `ruff check src/quant/data/mappers.py tests/unit/test_tushare_connector.py` | 通过 | `All checks passed!` |
| `mypy src/quant/data/mappers.py tests/unit/test_tushare_connector.py` | 通过 | `Success: no issues found in 2 source files` |
| 全量 pytest / HK history 回填 / 网络 / Tushare / WSL Gate / 真实 retained raw 再发布 | 未运行 | 初验范围外；不得据此宣称 Gate |

Pandera/Polars `concat(how='horizontal')` DeprecationWarning 与 `.pytest_cache` 写入拒绝为环境噪声，不改变结论。

---

## 清理与范围审查

- 临时探针已删除；未修改生产代码、实现者测试、任务单、交付报告。
- 未在 mapper 中发现港交所价位表复制。
- README 仅同步该 mapper 段，与冻结规则一致。
- 工作区另有并行改动（`docs/quant_factor_research_v2/` 等）；本会话未触碰，也不将其计入本初验。

---

## 结论

**PASS**。进入主 Agent 最终验收。

本初验只证明：白名单内的 HK close-only 有界包络与任务单、对抗反例、定向测试/Ruff/mypy 一致。  
**不宣布** M1 完成，**不宣布** HK60 Gate 通过；真实 retained raw 重跑、clean 再发布与 WSL Gate 仍待主验。
