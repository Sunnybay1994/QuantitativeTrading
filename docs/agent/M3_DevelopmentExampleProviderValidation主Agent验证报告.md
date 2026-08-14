# M3 Development Example Provider Validation 主 Agent 验证报告

日期：2026-07-31
结论：**开发 G2C fresh-process 公共 API 契约通过；正式 G1/G2C/M3 Gate 未据此关闭**

## 1. 边界

本轮只消费隔离的 `VerifiedDevelopmentExampleSnapshotArtifact` 与
`VerifiedDevelopmentExampleProviderArtifact`。开发 validation 使用含固定 domain tag 和 `example_id` 的 key、
`development-provider-validation` receipt stage、同时含 `development`/`example` 的输出根，以及
`VerifiedDevelopmentExampleProviderValidationArtifact(release_kind="development_example",
formal_gate_eligible=False)`。正式入口精确要求正式 nominal 类型，开发对象不会成为
`VerifiedProviderValidationArtifact`。

fixture 为 21 个连续交易日和三个 A 股证券；`000001.SZ` 在一个全日停牌日无行情并恰有 20 个 emitted rows，
另两证券各 21 行。公司行动/复权和证券退市生命周期边界仍在同一 fixture 中。正式
`provider_market_stratified_hash_first_last_v1` 未放宽：3 个证券各 20 日期、七字段，共 60 keys/420
emitted comparisons；一个 gap 另计 7 comparisons。

## 2. 实现

- `contracts.py` 增加冻结的 probe/spec/summary/result/verified value objects。
- `provider_validation.py` 负责确定性分市场 hash 抽样、fresh 子进程启动、父进程重算 expected/bit pattern、
  calendar/instrument 对账、确定性 details/summary 和 receipt 验真。
- `qlib_adapter.py` 是唯一允许 import Qlib 的 worker；父模块和 `quant.research.m3` 公共 import 路径不 import
  Qlib。worker 只写原始逐 cell/API 摘要，不写 `passed`。
- summary strict reader 拒绝字段漂移、duplicate JSON key、非规范 JSON 和非有限 JSON 数。

## 3. 验证证据

Windows Miniforge：定向 Ruff、mypy 通过；开发示例/G2B 回归 `22 passed, 2 skipped`；G2C 定向套件
`38 passed, 2 skipped`。对抗测试覆盖确定性计划、60/420 与 gap 分计、开发 nominal 边界、finite/±Inf gap、
emitted NaN/±Inf、raw dtype、timeout、identity echo、父进程预载 Qlib、summary wholesale drift、同字节错路径、
hardlink、完整 sampling/key 重算、hash tie、缺市场/19 行、missing/extra/duplicate、显式 gap NaN、
calendar/instrument 漂移、nonzero/坏 Parquet、timezone/non-midnight 和错误 key 前置拒绝。

WSL `py312`（Python 3.12、pyqlib 0.9.7）执行无网络真实 pinned dump + fresh public API smoke：
`1 passed`；真实结果为 60 emitted keys/420 comparisons、1 gap/7 comparisons，calendar/instrument 对账通过。
WSL base 对应 Ruff/mypy 通过，G2C 定向回归 `39 passed, 1 skipped`；跳过项是显式 py312
real-Qlib smoke，不代表正式 Gate。WSL `py312` 的无网络真实 public-API smoke 为 `1 passed`。

最终对抗补充覆盖 `+0.0/-0.0` float32 bit、坏 worker JSON/字段顺序、Qlib MultiIndex
逆序/改名、两个不同 validation identity 连续执行时的独立临时 request/response，以及 snapshot/provider
中未声明空目录。编排层在调用 validation 前仍必须通过公开 verifier 新鲜重验 snapshot、provider 及其
receipt；validation API 接收的 nominal artifact 不是跳过 receipt 重验的授权。

## 4. 初验返工闭环

第一轮独立初验为 FAIL（6 个 P1、2 个 P2）。以下通过条件均由新增测试和第二轮独立复验共同确认：

| 现象 | 根因与应遵循规则 | 最小复现 / 新增测试 | 通过条件 |
|---|---|---|---|
| summary 可整体替换 | verifier 只验少数字段；必须从持久 details 和 verified 输入重算 | 改 60/420、probe/read hashes 后重发 receipt | wholesale drift 被拒绝 |
| receipt 同 hash 错路径可混入 | 只比较 SHA Counter；receipt 身份包含 alias/path/size/hash | provider manifest 复制到 decoy | 完整 snapshot/provider tree 与 request/receipt 精确闭包 |
| gap ±Inf 被当 NaN | 只判断 non-finite；仅 NaN/absent 合法 | gap 返回 `+Inf/-Inf` | 七个 gap cell 计失败 |
| emitted NaN 被计 missing | worker 把 NaN 归一为 null；row-present 非有限需保真 | emitted 返回 NaN/±Inf | missing=0、non-finite=1 |
| instrument 多段被截断 | worker 只取首段；API 摘要必须全闭包 | 同证券返回两个 ranges | worker 明确失败 |
| reader 泄漏异常/错误码漂移 | 边界未覆盖 JSON read；须遵循任务书三错误码 | `{`、timeout、bad dtype | 只返回冻结 code |
| raw dtype 可宽松转换 | 只验列名；worker protocol 包含精确 dtype | Boolean 改 Int64 | worker failed |
| 链接可绕过物理闭包 | 直接 resolve/read；产物必须普通单链接文件且祖先无 reparse | hardlink summary、symlink parent | verifier/preflight 前置拒绝 |
| 任意 60 keys 可冒充 sampling | verifier 从 details 反造“期望计划”；必须从 verified inputs 重跑冻结 policy | 用未选内部日替换 hash-selected 日期 | details keys 与权威 plan 精确相等 |
| validation key 可整套替换 | summary 无 code version 且 verifier 无可信 spec；key 必须独立重算 | 同改 summary key、receipt scope、plan hash | verifier 接收 `ProviderValidationSpec` 并重算 formal/dev key |

第四轮复验发现原 A→B 用例只更换 validation key、未更换 provider URI。最终补测构造两个不同
provider code version/key/root/URI，逐次验证并确认 worker 命令入口、request/response/details 临时路径
和父进程 Qlib import 隔离。Windows 与 WSL base 单例均为 `1 passed`；最终只读复验为 PASS，剩余
P0/P1/P2 均为 0。

## 5. 未关闭事项

开发结果不证明正式 G1 发布、正式 snapshot/provider/provider-validation、真实数据覆盖或性能，也不关闭
G2、G3、M3、G9 或 Linux 正式 Gate。正式 G2C 必须等待正式 G1 完成后，从正式 nominal artifact 链重新执行。
