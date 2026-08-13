# M3 G8C-C0 F0 R3：续跑 Provider 至 Resolver 任务单

日期：2026-08-11

状态：**F0 R3→R5 外部闭环及主 Agent 最终验收 PASS（2026-08-12）；诚实 public chain、owned-cleanup 来源绑定与 fixture teardown 零残留均已闭合。见 [C0 主验报告](M3_G8C_C0_R3_配置原路径锚定与全链Integration主Agent最终验收报告.md)**

## 1. 前提与目标

F0 R2 已在 Windows `m3chain312` 通过 public G1（18 文件）与 snapshot，并交付 4 个 support 模块（1139 行）和
C0 integration 骨架；唯一阻断是 conda `python.exe` hardlink。F2 已完成外部实现、独立初验和主验，用专用 Windows
handle 安全闭合 current interpreter，且未放宽通用单链接规则。

本轮不得重写已通过的 G1/snapshot support；只做使现有链继续通过
`provider → provider-validation → experiment → label/folds/feature → alignment → model → prediction → target →
backtest_plan → resolve_formal_backtest_cli_inputs` 的最小测试侧修正，并取得 actual integration 终态。

## 2. 实现边界

- 解释器 exact `D:\Miniforge3\envs\m3chain312\python.exe`，cwd 当前 m3-g4-formal，`PYTHONPATH=src`。
- 复用现有 `tests/support/m3_formal_public_chain/` 四模块；总行数仍不得超过1300，不得第五模块。
- 只允许项目已冻结的 deterministic external worker / LightGBM process boundary；每项必须列入报告。禁止 fake verifier、
  private issuer/helper、production monkeypatch、`SimpleNamespace`、`object.__new__/__setattr__`、replace verified、固定
  runtime/dependency/provider identity。
- F2 production/tests在本轮只读；不得为后续层失败修改任何 production/schema/config。
- 保留 owned temporary project/config/G1/stage roots；每轮失败/成功后按实体 owned-only 清理，不复用失败半成品。
- 先用单个 actual happy-path 节点定位；每次长链自然结束后才可最小修正并重跑，禁止并发或重复长链。

## 3. Integration 完成条件

1. actual public chain 从 G1 到 backtest_plan receipt 全部成功，所有 verified 值由 public verifier返回；
2. exact 一次调用 resolver，返回字段可直接绑定 `run_formal_backtest_stage`，但不运行 StageRunner；
3. resolver 前后 G1/stage tree 零写；同一 session 第二次 resolver 只读重验且逐字段等价；
4. public verifier exact-once/order按 F0 R2 合同旁路观察；decorator不可判部分需actual+静态映射并诚实记录；
5. plan receipt缺失、config source实体替换、runtime/config漂移、跨平台复用均稳定拒绝、cause/context脱敏、零写；
6. WSL base/py312在任何链写入前因 no-replace capability=false exact skip，非PASS。

## 4. 白名单

- `tests/support/m3_formal_public_chain/__init__.py`
- `tests/support/m3_formal_public_chain/g1_inputs.py`
- `tests/support/m3_formal_public_chain/session.py`
- `tests/support/m3_formal_public_chain/stage_chain.py`
- `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`
- 更新本任务状态
- 唯一交付报告 `docs/agent/M3_G8C_C0_F0_R3_续跑Provider至Resolver交付报告.md`
- 独立初验只写 `docs/agent/M3_G8C_C0_F0_R3_续跑Provider至Resolver独立复验报告.md`

禁止改 production、F2 tests、unit tests、config/pyproject/lock、其他docs、环境；禁止联网/add/commit。

## 5. 验证与停止条件

Windows actual integration 单轮最长7200秒；通过后跑定向 Ruff/mypy/cold/diff。记录各stage耗时、文件数和清理终态，
不回传完整日志。独立初验必须用全新外部会话自己跑 actual happy path，并新增至少一个未用 hostile 反例。

若出现新的 production API/schema真实冲突、support需超1300行/第五模块、只能靠禁止项、正式data/联网、cleanup不安全、
或单轮超7200秒无终态，立即停止并给出最小复现，不扩大白名单。

F0 R3 只可声明“Windows诚实public formal chain support工程合同PASS”。主验PASS后才进入C0 resolver整体主验；
不直接解锁C1，Linux ext4 Gate保持开放。
