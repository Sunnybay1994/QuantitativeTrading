# M1-HK-CA-P0 R2 retained bytes 与异常链脱敏 — 返工交付报告

日期：2026-08-09（Asia/Shanghai）  
状态：**R2 已交付，待全新独立上下文复验；不自行宣布 P0 开发合同或任何正式 Gate 通过**

## 结果

- 修复 F1：`_validate_bundle` 在每次消费时逐个 fresh 验证 raw file 的对象类型、role、bytes 类型/非空、声明摘要格式，并重新计算 `content` 与 `metadata` SHA-256。构造期 frozen/dataclass 不再作为消费期可信依据。
- 修复 F2：source adapter preflight、projection factory、selector 和 result verifier 捕获稳定错误时只保存 `code`；退出 active `except` 后创建全新 `HkCorporateActionError` 并 `raise ... from None`。未知异常按各入口原有冻结错误码映射。
- 保持未变：schema、identity 算法、Protocol、revision/predecessor、withdrawal、`published_at` no-lookahead、错误码集合及与复权/账户/真实来源的隔离。
- 修改仅涉及既有白名单中的 `src/quant/data/hk_corporate_actions.py`、`tests/unit/test_hk_corporate_actions.py` 与本报告；P0 R1 的其他白名单改动保留。

## 失败闭环与证据

| 初验问题 | 根因规则 | R2 实现 | 新增测试 / 结果 |
|---|---|---|---|
| frozen raw `content` 漂移仍被 selector 接受 | 消费入口必须 fresh 重算实际 bytes，不信任构造期校验 | `_validate_bundle` 每次逐文件重算 content/metadata SHA-256，然后才验证 bundle/projection/selection | 分别篡改 content、metadata、两者；selector 与 result verifier 均稳定 `HK_CA_EVIDENCE_INVALID`，cause/context 为空，traceback 无 marker |
| hostile adapter 的稳定错误保留 active exception context | 稳定 error code 不等于稳定 exception object | `verify_hk_corporate_action_source` 保存 code，离开 except 后重构异常 | 六个允许码 × direct/ValueError/RuntimeError 三类，共 18 组合全部保留 code 且 cause/context 为空；未知 RuntimeError 映射 evidence invalid |
| factory/selector/verifier 内部稳定异常可能嵌套泄漏 | 所有公开消费者边界采用同一“保存 code → 离开 except → 重构”规则 | 三个入口均最小局部重构，没有引入通用异常框架 | monkeypatch hostile nested stable error；三个公开入口均得到干净 `HK_CA_REVISION_CONFLICT`，marker 不进 traceback |

## 验证

| 平台 / 命令 | 结果 |
|---|---|
| Windows 专用 R2 测试 `test_hk_corporate_actions.py` | `36 passed` |
| Windows `test_schemas.py + test_hk_corporate_actions.py` | `90 passed` |
| Windows 定向 Ruff | `All checks passed!` |
| Windows 定向 mypy（3 个生产文件） | `Success: no issues found in 3 source files` |
| WSL base `/mnt/f` 同一 pytest 集合 | `90 passed` |
| WSL base 定向 Ruff | `All checks passed!` |
| WSL base 定向 mypy | `Success: no issues found in 3 source files` |

WSL 测试位于 `/mnt/f` DrvFS，只是双平台开发合同证据，不是 Linux/ext4 Gate。

## 清理、范围与未验证事项

- 未联网、未读取 token、未安装依赖、未调用 connector/SDK、未扫描或写入正式 data/journal/candidate/release、未触发 U0C 任务。
- 未修改 enums、schema/identity/revision/as_of 合同、HK history、M3、backtest 或 execution。
- 任务开始前已有的 HK history/HKEX/HK60/U0C 改动、报告和 pytest 目录均未清理、未认领。
- 未 add/commit。
- 真实 HK 来源格式、许可、revision/withdrawal completeness、复权/total-return、M1 与 ext4 Gate 均仍待后续独立证据。
- 下一步必须由未参与 R2 实现的全新独立 Agent 复验 raw fresh digest、异常对象链及至少一个新增对抗反例，再由主 Agent 裁定。
