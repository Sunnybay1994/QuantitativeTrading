# M3 G8C-C1 U4 R1：owned 残留精确清理与单次业务边界诊断任务单

日期：2026-08-12  
状态：**U4-B 已收口：cleanup dry-run+real PASS（三项 REMOVED、现地 absent）；handshake PASS（EXIT=0）；唯一 Diagnostic FAIL（EXIT=1；setup/passed→call/failed）；首失败边界 `simulate_formal_a_share_scenario` call#1 multiplier=0.5 / `AShareSimulationError`；CLI `STAGE_BUILD_FAILED`/5；14 边界 U3 全零→U4 十边界有事件；禁止重跑 U4 Diagnostic；待主 Agent 冻结 §5 最小实现返工**  
报告：[M3_G8C_C1_U4_R1_owned残留精确清理与单次业务边界诊断报告.md](M3_G8C_C1_U4_R1_owned残留精确清理与单次业务边界诊断报告.md)  
上游：[M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断报告.md](M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断报告.md) **仪器 PASS / setup 前 owned 残留阻断**

## 1. 唯一目标

精确验证并清理由 U1 中断遗留的三项 honest-chain owned fixture 实体；随后在全新的外置仪器目录先通过秒级
handshake，再由主 Agent 托管一次新的 Windows honest public-chain Diagnostic，首次进入 G7F 14 个业务边界
并定位 `STAGE_BUILD_FAILED` 的首个内部失败点。

U4 仍是诊断任务，不修改产品、不冻结修复、不宣布 C1/G8/G7F/Gate。

## 2. 已冻结 owned residue（exact 三项）

工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`

| 相对路径 | kind | `(st_dev, st_ino)` | 内容/树 SHA-256 | 文件/目录数 |
|---|---|---|---|---:|
| `configs/research/_m3_f0r2_chain_session.toml` | regular file | `(3748812683449010654, 11540474045569937)` | `cd01fd633ba67bf528ee302379e412c0fa46f348c792e286a620463809faf5d1` | 1 / 0 |
| `artifacts/research/m3/_f0r2_6a18925ce6a8` | directory | `(3748812683449010654, 11258999068859280)` | `a2302d2fb495c50fe54e0791bb74204675432d362bb20780620eef399df2ddbe` | 2433 / 335 |
| `data/clean/m3_g1/releases/58a53a3be42ef34c3aa0984ca5571d976542aab7991ad074e5a760b975db222f` | directory | `(3748812683449010654, 11258999068859282)` | `58c1aa012385309a626068feab072b96563f5ae17bed7e256c75569776f43ad2` | 18 / 0 |

树摘要算法：按 relative POSIX path 排序；regular file 记录 `F\0<rel>\0<size>\0<content_sha256>\n`，目录记录
`D\0<rel>\n`，其他实体记录 `O\0<rel>\n`，整体 SHA-256。配置为原始 bytes SHA。

本地脱敏证据：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u3-owned-residue-sanitized.json`。
它证明配置逐字匹配 `_write_owned_config` 生成规则、引用 exact stage shape、三实体创建时间落在 U1 窗口、G1
release 是该窗口唯一候选、均非 link/reparse。外部 Agent **禁止读取配置正文**。

## 3. U4-A：外部 Cursor `auto` 准备

新目录必须尚不存在：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u4-r1-g8-build-diagnostic\`

U4-A 只允许：

1. 读取本任务、U3 报告、脱敏证据、support cleanup 源码；禁止读取配置正文；
2. 在新目录创建 `cleanup_u4_owned.py`、U4 plugin/wrapper/handshake probe/test、准备证据；
3. cleanup 脚本仅接受无参数运行，根目录/三相对路径/token/kind/count/SHA全部内嵌冻结；不接受 caller path；
4. cleanup 默认先完整重算三项身份与摘要，任一漂移/缺失/link/reparse/other entity立即非零退出且零删除；
5. 所有预检通过后才按 support 语义删除：两个目录内部按深度逆序删除 regular files和空目录，禁止跟随 link，
   最后删除根；配置用 exact regular-file unlink；不得触碰父目录或其他项；
6. 每删除一个根前后记录脱敏状态，结束验证三路径均不存在；写 exclusive cleanup evidence；
7. 只执行 py_compile/Ruff/PowerShell AST/import/边界存在与**只读 dry-run**；不得执行真正清理，不得启动真实链；
8. U4 仪器沿用 U3 已验证合同，但所有文件/env/name改为 U4，新目录 no-clobber；handshake 可执行且必须 PASS。

U4-A READY 后只更新任务状态，不创建最终 U4-B 报告。

## 4. 主 Agent 精确清理 Gate

主 Agent审核脚本后，在无 Cursor writer、pytest、m3chain312 进程时：

1. 再独立重算 §2 三 token/kind/count/SHA；
2. 核对 cleanup dry-run 输出 exact MATCH；
3. 只运行一次 `cleanup_u4_owned.py`；
4. 读取明确整数 EXIT、cleanup evidence，确认 exact 三路径不存在；
5. 报告用户：删除的是不可恢复的 U1 生成 fixture residue，不是正式 data/config；
6. 任一漂移立即停止，不删除任何项。

禁止用 glob、环境变量、工作树根、父目录或模糊时间窗作为删除目标。

## 5. U4 Handshake 与唯一 Diagnostic

清理成功后，主 Agent核对 U4 handshake 已 PASS、integration SHA 仍为
`5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2`、Diagnostic 文件不存在且无并行
writer/pytest，再启动唯一 Diagnostic。U4 plugin必须 exact nodeid、protocol级安装、setup/call/teardown lifecycle、
14边界透明包装；wrapper必须排空 stdout/stderr 并写整数 EXIT。真实链预算10800秒，不重跑。

## 6. U4-B 独立只读取证

唯一链结束后，另一全新 Cursor `auto`：

- 只读 U4 evidence/observe/stdout/stderr 和 production/tests；
- 写唯一 `docs/agent/M3_G8C_C1_U4_R1_owned残留精确清理与单次业务边界诊断报告.md`；
- 更新任务状态；
- 给出首个失败边界、前后调用次数、异常 exact type/public code、分类、最小实现白名单与秒级回归；
- 不补跑、不清理、不改产品。

## 7. 文件白名单与安全边界

仓库永久写入仅本任务状态和唯一 U4-B 报告；production/tests/support/config/schema、正式 artifact/data、历史
任务/报告只读。系统临时目录仅 U4 文件。唯一被删除的是 §2 三个 exact generated fixture residue；禁止联网、
add/commit/push、秘密或其他删除。外部 Cursor 不得读取残留配置正文。

## 8. 停止条件

三项任一 token/kind/count/SHA漂移；出现 link/reparse/other entity；脚本需要参数或模糊路径；dry-run非MATCH；
U4目录已存在；handshake失败；边界漂移；integration SHA漂移；存在其他writer/pytest；需要改仓库代码；第一次
U4 Diagnostic已启动后要求重跑。命中即停止，零删除或不再继续，不猜产品根因。

## 9. 通过条件与后续

U4 完成必须同时有：三项精确清理证据、handshake PASS、唯一 Diagnostic 明确整数 EXIT、完整 lifecycle/业务
observe、全部证据 SHA 和 U4-B 报告。只有报告定位到可复现产品/fixture边界，主 Agent才冻结最小实现返工，
随后进入外部实现—独立初验—主验闭环。
