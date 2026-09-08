# FRAMEWORK M1/M3/M4 Current State Refresh R1 任务书

日期：2026-08-28<br>
状态：`FROZEN / STATIC_ONLY`

## 1. 身份与目标

- task id：`FRAMEWORK-M1M3M4-CURRENT-STATE-REFRESH-R1`
- exact base：`3e74dd7d4a43fc09b8e6f361dd183da55f9576cc`
- branch：`codex/framework-m1m3m4-current-state-refresh-r1`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\framework-m1m3m4-current-state-refresh-r1`
- 经理 exact2 最初在 clean `main` 形成，后由中央逐字迁入上述独立 worktree；迁移后 SHA 保持一致，后续所有角色只在该 worktree 工作。
- 目标：把 `M1_M3_M4_框架开发总路线图.md` 从 2026-08-16 历史快照刷新为当前 Git、archive tag、worktree 和用户 Gate 事实，消除“代码已合流但导航仍写未实现”的漂移。

本任务只维护框架动态导航，不改变根项目路线图、用户授权、业务 Gate、runtime/config、代码、测试、运行证据或 retained 现场。

## 2. exact4 与角色

1. `docs/framework/tasks/FRAMEWORK_M1M3M4_CurrentStateRefreshR1任务书.md`（经理写）
2. `docs/framework/roadmaps/M1_M3_M4_框架开发总路线图.md`（经理写 exact hunks）
3. `docs/framework/deliveries/FRAMEWORK_M1M3M4_CurrentStateRefreshR1交付报告.md`（实现者写）
4. `docs/framework/reviews/FRAMEWORK_M1M3M4_CurrentStateRefreshR1独立初验报告.md`（独立 reviewer 写）

当前经理阶段只写路径 1–2；路径 3–4 暂不存在。禁止修改 `docs/governance/**`、根路线图、AGENTS、代码、测试、config、其他任务文档或 evidence。

## 3. 必须写入的当前事实

### M1

- Windows 研究数据闭环已被 main 吸收，当前无 M1 待合流业务写面。
- 旧 `m1-hk60-integration@1d9b4e0` 是 main ancestor，但无 archive tag且含 ignored agent_runs/test_tmp/cache；只能列为退出审计候选，不能宣称已退休。
- Linux 不在本轮范围；不得把 Windows 结果扩大为跨平台 Gate。

### M3

- R2A executable upstream、R2I physical receipt identity、R2W package-owned downstream wiring、R2B production bridge/CLI、R2C actual-run admission均已进入 main。
- 这只关闭 Windows 静态/定向工程与运行准入；actual successor、真实 Qlib、新 root、retained 继承和 Linux Gate仍未执行。
- detached retained `c9f2f36` 继续 `LOCKED / terminal FAILED`，失败证据与两份既有 session config不得恢复、清理、重签或继承。
- R2C source `e8e35c9` 已归档且无 ignored 残留，是可做最终 process/lock审计的退休候选；R2W rebuilt `5059255` 虽已归档但有 ignored validation evidence/cache，未获处置前保留。
- 未提交的旧 R2B/R2W 事故现场不得与已合流 rebuilt/source混淆，禁止机械删除。

### M4

- B1B2 terminal closure、P1 canonical broker cost、P2 broker materialization identity、fresh formal bootstrap、bootstrap regression fix、operator CLI已进入 main。
- R2 CLI source已 archive-first退休；Windows工程闭包不等于真实 bootstrap、PAPER、soak、UA-M4-006或Linux Gate。
- R3 run-only worktree已在 `aa84ebc` 冻结，当前仅 taskbook dirty；external parent/config/five roots/epoch均不存在，等待用户逐字 A–D 授权。
- A–D 分别控制 parent+config创建、一次 initialize、核验后一次 reopen、成功/失败现场 LOCKED保留；不得把自动续跑或笼统批准解释为授权。
- 旧 P2/R1/R1-rebuilt dirty事故现场保留，只能在中央精确字节/身份审计和处置裁定后退出。

### 跨域与 M2 边界

- main current safe point 为本任务 exact base；M2 R18已合流在其祖先 `721133b`，但真实 Run1 在发布前因 chosen outcome exact-one-null停止，三候选为 `UNASSESSED/HOLD`，无run_id/manifest/13 outputs。
- R18 source已归档，exact13 ignored evidence未获不可恢复删除授权，来源 worktree/branch继续保留。
- finance writer当前 absent但非 authoritative terminal；cashflow exact1365恢复集合已在治理SSOT冻结，必须用户逐字批准后才可单writer单pass恢复。

## 4. 事实来源与防漂移

只允许引用：

- `git log --first-parent main`、`git merge-base --is-ancestor`；
- annotated archive tag与source commit；
- `git worktree list --porcelain`、各worktree status/ignored preflight；
- 已合流 task/delivery/review与 `docs/governance/用户待批示与参与事项.md`。

不能用旧路线图文字证明当前事实，不能以 dirty 推断完成，不能以 archive tag替代worktree退出审计。commit短 SHA必须能从当前仓库解析；运行/Gate状态必须采用“不足即OPEN”的保守表述。

## 5. 失败语义与反例

- 发现 main/base、archive指向或worktree状态与任务书不一致：`STATE_DRIFT_STOP`，保留现场。
- 发现需要修改用户事项、根路线图或代码来“协调”差异：`WHITELIST_STOP`，不得扩 exact4。
- 反例：某source commit已是main ancestor且已有archive tag，但仍含ignored evidence；路线图必须写“已合流/已归档、未退休”，不得写“已退出”。
- 反例：M4 R3 taskbook已冻结但A–D未授权；必须写“等待用户授权”，不得写“运行中”或“真实bootstrap完成”。
- 反例：M3 R2C只是运行准入文档合流；不得把它写成actual successor已经执行。

## 6. 验收

STATIC_ONLY，无 Python、pytest、Ruff、mypy、cold、网络或真实 I/O。完成时至少验证：

1. scope按角色阶段闭合：经理交接为taskbook+roadmap exact2，实现交付为exact2+delivery exact3，独立审查为完整exact4；各阶段cached0、无额外路径；
2. 普通 `git diff --check` PASS；两文档UTF-8、无trailing whitespace、单一EOF LF；
3. main/current commit链与路线图引用可解析；
4. 路线图明确 M1/M3/M4已闭合、OPEN、LOCKED、STOP与退休候选；
5. 不修改项目Gate SSOT、UA条目或任何运行现场。

实现者只写delivery记录diff与静态证据；不同reviewer必须补查至少一个“ancestor但不等于retired”的反例并输出 `REVIEW_PASS/FAIL`。通过后再申请安全提交，不自行stage/commit。
