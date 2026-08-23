# M3 G8C-C0 F0 R2：Windows 诚实 Formal Public Chain Support 任务单

日期：2026-08-11

状态：**外部实现已停止（Windows m3chain312 `python.exe` st_nlink=2 与 production `_read_regular` nlink==1 互斥，阻断 public provider materialize）；已交付 support/integration 骨架与停止证据；不宣称 F0/C0/C1 PASS；待主 Agent 复核**

## 1. 前提与目标

F0 R1 已诚实证明 WSL1/DrvFS 不支持 formal publisher 所需的 atomic directory no-replace。F1 已完成并主验
Windows `D:\Miniforge3\envs\m3chain312`：Python 3.12、Qlib、LightGBM、PyArrow、provider fingerprint 与 public
no-replace 能力均可用。本轮只在该环境构造一次 pytest session 内的真实 public formal chain：

`G1 → snapshot → provider → provider-validation → experiment → label/folds/feature → alignment → model → prediction
→ target → backtest_plan`。

该 support 只服务 C0 integration；不新增 production API，不产生长期金样，不运行 StageRunner/G7F/tracking/CLI，
不读取根项目正式 data，不联网或启动 MLflow 服务。

## 2. 平台与解释器

- Windows actual 必须使用 exact `D:\Miniforge3\envs\m3chain312\python.exe`，cwd 为当前 m3-g4-formal worktree，
  `PYTHONPATH=src`；解释器、provider fingerprint、public no-replace 任一漂移都在写文件前停止。
- Windows actual 不得 skip。WSL base/py312 因 WSL1 no-replace capability=false，只能在任何链文件写入前以 exact
  capability reason skip；不得 monkeypatch `_renameat2_noreplace`。
- Windows 证据只算工程合同，不替代 Linux ext4 Gate。

## 3. Test-only support

新增 `tests/support/m3_formal_public_chain/`，最多四个模块、生产性 support 总计不超过 1300 行：

1. session/locator 与 owned-root cleanup；
2. 纯 raw G1 input/reference-response fixture；
3. G1 public publish/verify；
4. snapshot 到 backtest_plan 的 public stage 链。

可以把职责进一步压缩，但不得增加第五个模块。support 返回普通 locator/context 与真实 public verified values；不得
新增第二套 identity、receipt、schema 或 verifier。允许复用既有测试中的纯 raw 数据工厂或 deterministic external worker
边界；不得复用 verified capability、私有 issuer/helper、fake verifier、`SimpleNamespace`、`object.__new__`、
`object.__setattr__`、对 verified 值 `dataclasses.replace`，不得 monkeypatch production builder/verifier/publication。

若完整诚实链在 1300 行内仍无法表达，或需复制 production 验证逻辑，立即停止重冻。

## 4. 发布、身份与清理合同

- 使用真实 `load_m3_config`、`compute_m3_runtime_identity`、`build_provider_runtime_fingerprint`；所有 identity/hash/receipt
  来自当前 public 返回值，禁止固定 code/dependency/provider identity。
- G1 必须由 public `publish_g1_release` 发布并由 public `verify_g1_release` 恢复；正式 G1 树 exact 18 文件、无 receipt。
- 下游每层只用 public builder/publisher、`publish_stage_receipt` 与 public verifier，直到 exact backtest_plan receipt。
- 写入只限当前 worktree 下本 session 创建的 ignored G1 release 与 `artifacts/research/m3/**` 测试根。开始前 no-clobber；
  结束后只删除本 session owned 且实体仍匹配的路径。失败、异常和 pytest teardown 同样 owned-only 清理。
- 禁止写 `data/clean` 或 `artifacts/research/m3` 的用户既有树；若配置默认根会碰既有路径，必须使用 task-owned 临时
  project root/config copy，并保持 config bytes/runtime identity 闭包诚实，不得改 repo config。

## 5. C0 integration

把 `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` 的永久 stop skip 替换为 actual happy path：

1. session support 完成后 exact 一次调用 `resolve_formal_backtest_cli_inputs`；resolver 前后所有 G1/stage tree 零写；
2. 返回值可直接绑定 `run_formal_backtest_stage` public 签名，但本任务不运行 StageRunner；
3. 真实 public verifier exact-once/order 优先用 `sys.setprofile`/`sys.settrace`按 code object 观察，不 wrap/patch production。
   若 decorator 使部分计数不可判，须结合源码静态映射与 actual success，并在报告列明限制；
4. 删除 backtest_plan receipt、config source 实体替换、当前 runtime/config 漂移、跨 platform 复用旧树均 fail-closed、
   cause/context 脱敏、零输出写入；
5. 同一 session 第二次 resolver 必须只读重验且返回逐字段等价结果，不重建链。

## 6. 白名单

- 新增 `tests/support/m3_formal_public_chain/__init__.py`
- 新增最多三个同目录 support 模块
- 修改 `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`
- 更新本任务状态
- 唯一交付报告 `docs/framework/agent/M3_G8C_C0_F0_R2_Windows诚实FormalPublicChainSupport交付报告.md`
- 独立初验只写 `docs/agent/M3_G8C_C0_F0_R2_Windows诚实FormalPublicChainSupport独立复验报告.md`

禁止修改 production、unit tests、config、pyproject/lock、既有 G1-G8 tests/docs、正式 data/artifacts；禁止 add/commit。

## 7. 验证

Windows `m3chain312`：

- actual public chain + C0 integration 明确 PASS；单次链允许最长 7200 秒，已启动的长链低频等待、不得重复；
- 定向 Ruff/mypy/cold import/diff-check；support/import 不在 collection 时构造任何 artifact；
- 记录全链各 stage 耗时、文件计数、owned root 和清理终态；不得回传完整日志。

WSL base/py312：仅跑 capability gate，必须在零链写入状态 skip；不把 DrvFS skip 写作 PASS。

独立初验使用全新外部会话，必须自己在 Windows `m3chain312` 跑 actual happy path，并增加至少一个实现者未用的
config entity/receipt/runtime hostile 反例；production/实现测试只读，仅写独立报告。

## 8. 停止条件与声明

任一层只能靠私有 helper/fake verifier/verified 伪造/长期 bytes/正式 data/联网才能通过；actual chain 超过 7200 秒
无终态；support 超 1300 行或需第五模块；cleanup 无法证明 owned-only；任何真实 production API/schema 冲突；立即停止。

F0 R2 仅可声明“Windows 诚实 public formal chain test support 工程合同 PASS”。F0 主验 PASS 后才回到 C0 resolver
主验，不直接解锁 C1；Linux ext4 与正式 Gate 保持开放。
