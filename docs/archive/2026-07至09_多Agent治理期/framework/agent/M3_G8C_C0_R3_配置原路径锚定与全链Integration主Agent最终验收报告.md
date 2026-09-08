# M3 G8C-C0 R3：配置原路径锚定与全链 Integration 主 Agent 最终验收报告

日期：2026-08-12  
角色：主 Agent 最终验收  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md](M3_G8C_C0_R1正式BacktestCLI输入Resolver任务单.md)  
R3 交付：[M3_G8C_C0_R3_配置原路径锚定与全链Integration交付报告.md](M3_G8C_C0_R3_配置原路径锚定与全链Integration交付报告.md)  
诚实全链独立复验：[M3_G8C_C0_F0_R3_续跑Provider至Resolver独立复验报告.md](M3_G8C_C0_F0_R3_续跑Provider至Resolver独立复验报告.md)  
最终 R5 独立复验：[M3_G8C_C0_F0_R5_fixtureTeardown零残留观测独立复验报告.md](M3_G8C_C0_F0_R5_fixtureTeardown零残留观测独立复验报告.md)

## 结论

**PASS。M3 G8C-C0 formal Backtest CLI input resolver 工程合同完成，C1 可以冻结并进入“外部实现 → 外部独立初验 → 主 Agent 主验”流程。**

本结论只关闭 C0。它不代表 C1、完整 G8C、M3、真实 G1 数据范围或 Linux/ext4 Gate 通过；当前 WSL 仍为 WSL1/DrvFS（`wslfs`），其 `renameat2(RENAME_NOREPLACE)` capability=false 只形成安全拒绝与兼容证据。

## 1. 验收范围与闭环

C0 的最终实现由三个连续闭环共同构成：

1. R3 关闭配置原路径锚定、稳定实体/内容读取、13 层 public verifier 顺序与 exact-once、零写 resolver 以及可直接绑定 `run_formal_backtest_stage` 的完整返回值。
2. F0 R3 以真实 public G1→snapshot→provider→experiment/folds/feature/alignment/model/prediction/target/backtest-plan 链证明 resolver happy path；未使用 fake verifier、private issuer、`SimpleNamespace`、裸构造 verified capability 或 production verifier monkeypatch。
3. R4 关闭 owned cleanup 的 `(st_dev, st_ino, kind)` 来源绑定与 ABA/type/link/reparse fail-safe；R5 删除生命周期错误的轮询测试，把零残留断言放到 `public_formal_chain_session.__exit__` 完成后的 module fixture teardown 内。

R5 外部实现与独立复验由不同的全新 Cursor 会话完成，均按项目授权使用 `--model auto`；独立初验保持生产/support/实现测试只读，只新增唯一复验报告。

## 2. 逐项证据

| 合同项 | 当前权威证据 | 主验结论 |
|---|---|---|
| 配置必须绑定 caller 指定的 canonical 相对原路径、实体与 raw SHA；链接、hardlink、same-bytes 换 inode、跨 root 均在 runtime/verifier 前拒绝 | R3 unit、交付报告与 F0 R3 独立反例；当前 Windows resolver unit `17 passed, 1 skipped`，WSL base `18 passed` | PASS |
| 13 层 public verifier 真实链、depth-0 exact-once/order、返回值可直接绑定 StageRunner 且 resolver 不执行 StageRunner | F0 R3 独立 public-chain；R5 最终 revision 再次完整执行同一 honest chain | PASS |
| resolver 成功/失败均零写，异常稳定脱敏且 cause/context 为空 | R3/F0 R3 对抗、当前 focused unit 与 cold import | PASS |
| owned cleanup 仅删除原 session 所拥有实体；ABA、类型/link/reparse、检查异常均 fail-safe | R4 六个对抗；主验 Windows `6 passed, 6 deselected` | PASS |
| 零残留必须在 fixture teardown 内观测，不能靠 sleep/poll 或进程退出后扫描 | integration fixture L336–367；独立 TEMP 对抗证明 yield 时路径存在、`with` 后三路径消失且 report 含三条 `removed:`；逆断言产生 pytest ERROR/EXIT=1 | PASS |
| 最终 Windows honest public-chain 在 7200 秒内单次自然终态 | R5 独立复验：PID 21192，仅启动一次，`11 passed, 1 skipped`、EXIT=0、6846.60s；teardown 断言作为 pytest 生命周期执行 | PASS |
| WSL1 capability=false 时写前跳过且无残留 | WSL base cleanup/capability `7 passed, 5 deselected`；C0 unit `18 passed`；filesystem=`wslfs`/DrvFS | PASS（仅兼容，非 ext4 Gate） |
| 静态与冷导入 | Windows 项目反馈环境 Ruff 0.15.22、mypy、cold import PASS；WSL base Ruff 0.15.21 `All checks passed`、mypy `Success: no issues found in 7 source files`；冷导入不加载 Qlib/LightGBM/MLflow | PASS |

R5 最终文件身份与独立报告一致：

- `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` SHA-256=`D2D0BF6C2257D4AE429A2F909B13856D926C70F769116C3932F65A31CA2935F2`；
- `tests/support/m3_formal_public_chain/session.py` SHA-256=`B4AD0BF4BC181657F870D7800BD58A5518312E72F7146C1B2A6AEF531ADE5646`，证明 R5 未改 support；
- R5 独立复验报告 SHA-256=`778F72844636521AC518BB95D356EF334169937B74CFDB1D8C9D43BAC8510FDE`。

## 3. 主验裁决

### 3.1 F0 R3 的 7200 秒边界

F0 R3 独立轮曾为 7276.71s，功能绿但超过任务预算。R5 在最终 revision 上重新执行完整 honest chain，6846.60s、EXIT=0，且新增的 teardown 零残留断言真实执行，因此该边界已由更新、更强的证据关闭；不采用实现者丢失摘要或进程退出后扫描补成 PASS。

### 3.2 same-bytes plan receipt 实体替换

F0 R3 探针证明 plan receipt 的同内容实体重写可被内容身份接受。C0 冻结合同要求 config 原路径绑定实体与内容，而 plan receipt 延续上游 verifier 的内容身份；任务书未要求给每个上游 receipt 另加 inode authority。主验判定为合同边界而非缺陷，不在 C0 扩包。未来若提升为物理来源身份，必须先修改对应上游 SSOT/任务书并重新走独立闭环。

### 3.3 provider fingerprint 预检

session 的固定 provider fingerprint 是诚实 public chain 写入前环境门；artifact identity 仍来自当前 public runtime/provider 返回值。二者职责不同且未出现伪造 verified capability，判定非阻断。

### 3.4 Ruff 工具版本漂移

项目标准 Windows 环境 Ruff 0.15.22 与 WSL base Ruff 0.15.21 均通过。隔离 `m3chain312` 中 Ruff 0.16.2 会对稳定错误翻译边界的四处 intentional `except Exception` 报 BLE001；`pyproject.toml` 仅约束 `ruff>=0.4`。本轮不以非任务指定的升级环境改变生产合同，也不在主验直接改码；记录为工具链版本漂移风险，后续应在独立工具治理包中决定锁版本或显式标注 intentional broad catch。

## 4. 范围与遗留风险

- C0 只负责解析、fresh verification 与普通只读 resolution，不写 artifact、不运行 StageRunner、不连接 MLflow/网络。
- C1 必须在 `backtest` 命令调用栈内 exact 一次加载配置、exact 一次调用 resolver，再把其字段直接传给 `run_formal_backtest_stage`；不得新增 caller-supplied resolution、缓存、pickle 或恢复器。
- 当前工作树存在大量前序里程碑脏文件和历史临时证据，本次未删除、移动、add、commit 或覆盖；这些仍受未来合流策略与干净 checkout 复现 Gate 约束。
- Windows/DrvFS 证据不能替代 Linux ext4 Gate。

## 5. 最终裁决

**M3 G8C-C0 主验 PASS。允许立即冻结 C1 正式 Backtest 命令接线任务书并启动新的外部 Cursor `--model auto` 实现会话；C1 仍须由另一全新外部 Cursor `--model auto` 会话独立初验后，才能进入主 Agent 主验。**
