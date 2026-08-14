# M1-HK-CA-P0 来源无关 PIT 公司行动合同 — 实现交付报告

日期：2026-08-09（Asia/Shanghai）  
状态：**已交付，待独立初验与主 Agent 最终验收；不代表真实 HK 来源、M1 或 Linux/ext4 Gate 通过**

## 结果

- `CorporateActionSchema` 在既有 SSOT 上演进为 HK PIT canonical action，明确四类 action 的日期、币种和互斥经济字段；新增 `HkCorporateActionRevisionEvidenceSchema` 并从 `quant.domain` 导出。
- 新增 retained-bytes-only 的 query/capability/raw file/raw bundle/source Protocol/verified projection/selector/result verifier。没有 fetch、路径发现、默认目录或网络 fallback。
- same-event revision 从 1 连续、predecessor 精确闭包；PIT 只使用官方 UTC `published_at`，future correction/withdrawal 不前视；selected ACTIVE 与 tombstone evidence 均可 fresh 重建。
- canonical/evidence/projection 使用项目既有 `clean_table_content_sha256`；含 UTC datetime 的表先确定性规范化为 UTC ISO 字符串，再进入该版本化 canonical table hash。
- 修改文件：
  - `src/quant/domain/schemas.py`：canonical/evidence schema 与跨字段约束；
  - `src/quant/domain/__init__.py`：唯一新增 schema 导出；
  - `src/quant/data/hk_corporate_actions.py`：来源无关离线合同；
  - `tests/unit/test_schemas.py`、`tests/unit/test_hk_corporate_actions.py`：schema 与端到端 fixture/反例；
  - 本报告。
- 明确未修改：`enums.py`、connectors/base、M3、backtest/execution、HK60/history、U0C、G1、项目 `data/**`、正式 journal/candidate/release。

## 标准 → 代码/测试证据

| 成功标准 | 实现 / 测试证据 |
|---|---|
| 四类 action、CNY/HKD、单位与 null 分支唯一 | `CorporateActionSchema` 和 revision evidence schema；schema 测试覆盖 DIVIDEND、SPLIT multiplier=0.5、multiplier=1 及错放 `stock_ratio` |
| retained bytes/metadata/bundle fresh 摘要闭包 | `HkCorporateActionRawFile.create/__post_init__`、`HkCorporateActionRawBundle.create/__post_init__`；错误声明摘要稳定返回 `HK_CA_EVIDENCE_INVALID` |
| capability 在解析前 fail closed | `verify_hk_corporate_action_source` 先 `_preflight` 再调用 adapter；测试证明缺 withdrawal capability 时 adapter 调用次数为 0 |
| adapter 只解释显式 bytes | 测试内 `FixtureHkCorporateActionSourceAdapter` 严格解析一个内存 JSON retained file；生产代码无 fixture adapter、URL、token 或 SDK |
| revision/withdrawal 完整链 | `_select_frames` 重验 event key、sequence、predecessor、candidate identity、published_at 严增；测试覆盖 start-at-2、gap、错 predecessor、改 symbol、相同 published_at |
| no-lookahead | 原版 2026-05-04 09:00Z、更正版 2026-05-05 02:00Z；01:59:59 选 0.5，02:00 起选 0.6 |
| future withdrawal 不抹除历史 | 2026-05-06 02:59:59 保留 ACTIVE，03:00 后 canonical 消失且 `WITHDRAWN_AS_OF` tombstone selected |
| actions ↔ evidence/result digest fresh 闭包 | `verify_hk_corporate_action_selection_result` 重新构建完整结果并比较顺序、内容和两份摘要；action 漂移测试稳定 `HK_CA_RESULT_INVALID` |
| 同日不同经济事件不合并 | fixture 中四个事件共享 2026-05-11 `ex_date`，canonical 保留四行；event identity 不使用 `(symbol, ex_date)` 去重 |
| 稳定重放 | 同 projection 两次 selection 的 action/evidence digest 分别相同 |
| 跨层隔离 | import side-effect 测试确认模块导入不新增 requests/tushare/akshare/baostock/qlib；代码不 import connector、M3 selection、复权、回测或账本模块 |

## 验证

| 命令或检查 | 结果 | 证据摘要 |
|---|---|---|
| Windows `pytest tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py -q -p no:cacheprovider` | 通过 | `67 passed` |
| Windows 定向 Ruff | 通过 | `All checks passed!` |
| Windows 定向 mypy（3 个生产文件） | 通过 | `Success: no issues found in 3 source files` |
| WSL base `/mnt/f` 同一 pytest 集合 | 通过 | `67 passed` |
| WSL base 定向 Ruff | 通过 | `All checks passed!` |
| WSL base 定向 mypy | 通过 | `Success: no issues found in 3 source files` |
| `git diff --check`（白名单） | 通过 | 无 whitespace error；仅既有 LF/CRLF 提示 |

Windows 与 WSL 测试均使用同一 worktree；WSL 路径位于 `/mnt/f` DrvFS，因此这里只证明开发合同的双平台一致性，不是 ext4 发布 Gate。

## 清理与范围审查

- 未安装/升级依赖，未联网，未读取 token，未触发计划任务或正式数据流程。
- 本任务没有留下 pytest basetemp；测试输出只有既有 Pandera/Polars deprecation warnings。
- `git status` 中 HK history、HKEX-02983、HK60-01065、U0C 及既有 pytest 目录均为任务开始前的工作，未修改、未清理、未认领。
- 本任务新增/修改内容严格限于任务单实现白名单；未 add/commit。

## 风险与交接

- 未验证任何真实 HKEX/Tushare/其他授权来源格式、revision/withdrawal 能力、许可或全市场 coverage；真实 adapter 必须另冻来源专属合同。
- P0 不产生累计复权因子、total-return、FX/税费、供股认购或账户分录；这些 Gate 保持开放。
- `CorporateActionSchema` 是公共 SSOT 演进。当前仓库除本模块/测试外没有生产消费者；主 Agent 合流时仍应检查并行分支是否新增旧字段消费者。
- 需要新的独立审查上下文增加任务单指定对抗反例，尤其是 selected tombstone 伪造 canonical、future withdrawal 和输出 evidence 漂移；实现者不宣布项目 Gate 通过。
