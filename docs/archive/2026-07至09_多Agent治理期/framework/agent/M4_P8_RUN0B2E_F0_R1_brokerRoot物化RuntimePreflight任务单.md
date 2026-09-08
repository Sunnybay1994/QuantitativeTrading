# M4 P8 RUN-0B2E-F0 R1：broker root 物化态 Runtime Preflight 任务单

日期：2026-08-12  
状态：**外部实现、全新外部独立初验与主 Agent 最终验收均已 PASS；允许进入 B2E formal store opener**  
前置：RUN-0A R3、B2B、B2C、B2D R2 均已工程主验 PASS；B2E 外部只读设计审计已完成

## 1. 唯一目标

在不创建任何 root、不打开 SQLite、不实现 store/gateway/service 的前提下，把 RUN-0A 的 formal runtime layout 从“broker root 永久只能 absent”演进为两个可 fresh 签发且互斥的精确状态：

1. cold：五根全部 absent；
2. broker-materialized：仅 `broker_root` 是真实、非 link/reparse 的目录，其余 `runtime/evidence/anchor/log` 四根仍 exact absent。

这样后续 B2E store initializer 可先消费 cold capability 创建 broker root，再从同一 formal config 重新签发一条 broker-materialized runtime/policy/binding/account fresh 链。旧 cold environment 在物化后必须失效；不得让旧 attestation 跨状态继续有效。

## 2. 冻结实现语义

- public API 与 `__all__` 不变；不新增 caller mode、path、identity 或 `allow_materialized` 参数。
- `_build_layout` 只对 exact `FormalPaperRuntimeConfig` 接受 broker root 的两态；development config 继续要求五根全部 absent，行为不得漂移。
- broker root absent 时沿用 `absent-paper-runtime-root-v2` identity。
- broker root 存在时必须 exact real directory、非 symlink/junction/reparse，且父链真实；identity 使用新 canonical payload `materialized-paper-runtime-root-v1`，至少绑定 role、parent identity、leaf/resolved path、device、inode、directory mode。
- 其余四根出现任意 file/directory/link/reparse 都稳定 `PAPER_RUNTIME_LAYOUT_INVALID`。
- materialized broker root 内部文件树不属于 runtime 层身份；本包只证明根目录实体，store tree/descriptor/journal 由后续 B2E 验证。报告必须明确这一边界。
- `PaperRuntimeLayout.root_identities` 与 `layout_identity` 必须包含当前两态结果；cold→materialized 后旧 `VerifiedPaperRuntimeEnvironment` 的 existing verifier稳定失败，新调用 `verify_paper_runtime_environment` 可签发不同 identity 的 materialized environment。
- materialized broker root 被 rename/同 bytes 目录替换、改为 link/reparse、父目录替换时 existing verifier必须拒绝。
- verifier与错误翻译保持 cause/context `None`；不得泄露绝对路径、inode、hostile marker。
- 本包只读探测 filesystem；零 mkdir、零写文件、零 SQLite、零 network/socket/log/wall-clock。

## 3. 必测反例

1. formal cold 五根 absent 正向保持；development cold 正向保持。
2. formal 仅 broker root 为真实空目录可签发 materialized environment；目录内加入普通文件后 runtime capability仍有效（tree由store层负责）。
3. development broker root 即使是真实目录也拒绝。
4. runtime/evidence/anchor/log 任一物化均拒绝；broker root 为 regular file、symlink、junction/reparse均拒绝。
5. cold capability签发后创建 broker root：旧 existing verifier拒绝；重新签发 materialized capability成功且 verification/layout identity不同。
6. materialized capability签发后 same-path directory replacement、parent replacement、root变link/reparse：拒绝。
7. hostile `lstat`/identity异常递归 cause图脱敏且零写。
8. public surface/cold import不加载 soak/reporting/backtest；无新 signer/key/mint入口。

## 4. 白名单

允许修改：

- `src/quant/execution/paper_runtime.py`
- `tests/unit/test_paper_runtime.py`
- 本任务状态
- 唯一 `docs/framework/agent/M4_P8_RUN0B2E_F0_R1_brokerRoot物化RuntimePreflight交付报告.md`

禁止修改 B2B/B2C/B2D、paper broker store/gateway/service/CLI/soak、config、其他测试、正式 roots/data/journal。不得联网、add/commit/push。

## 5. 验证

Windows Miniforge：focused `test_paper_runtime.py`，并合流 runtime+policy+binding+account 定向节点；Ruff、mypy、cold import、scoped diff-check。当前阶段暂不考虑 Linux 实现/Gate；可记录 WSL/DrvFS 兼容结果，但不得要求或宣称 ext4 Gate。

## 6. 通过与停止条件

通过条件：cold 与 broker-materialized 两态均能由 actual public runtime verifier fresh 签发；状态转换使旧 capability 失效；其他四根保持 absent；development行为、public API与所有 RUN-0A 反例保持绿色。

若实现需要 caller 提供 mode/identity、需要检查或理解 broker tree、需要修改 B2C/B2D、需要创建 root/SQLite，立即停止并报告合同冲突。实现交付后必须由另一全新 Cursor `auto` 独立初验，PASS 后再由主 Agent 主验；B2E-F0 PASS 前不得实现 formal store opener。
