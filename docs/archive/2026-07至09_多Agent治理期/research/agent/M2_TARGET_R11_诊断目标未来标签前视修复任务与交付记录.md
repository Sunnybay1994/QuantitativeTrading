# M2 TARGET R11：诊断目标未来标签前视修复任务与交付记录

## 1. 状态与边界

- 状态：实现、定向开发检查、统筹合流、归档与来源线退休全部完成。
- owner：策略开发 session。
- branch：`codex/m2-target-label-leakage-fix`。
- worktree：`artifacts/dev_worktrees/m2-target-label-leakage-fix`。
- exact base：`532a067a0fb8ba8f1ac9a6ba1030d0bee29b5957`；不 rebase、merge 或 cherry-pick。
- source commit：`77058981e5be656c941c73be0d7e52d74fcecbe5`；integration no-ff merge：
  `864d254474a3cb050908c147e54bcc0c7d983167`。
- archive：`archive/m2-target-label-leakage-fix-20260816` 精确指向 source commit；source worktree
  与 branch 已 clean 退休。
- 本包只修研究诊断目标的选择时序，不运行真实研究、不改写任何 immutable run，也不产生
  `PAPER_CANDIDATE` 或启动 PAPER。

精确写白名单只有：

1. `src/quant/research/classic_factor_evaluation.py`；
2. `tests/unit/test_classic_factor_evaluation.py`；
3. 本记录；
4. `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的 R11 状态 exact hunk。

禁止修改 runner、config、Schema、repository、publisher、facade、formal replay、共享 SSOT、writer、
ledger 或 partial raw。PIT 四因子的固定方向 `(+,+,+,-)` 不在本包处理，留给 R3。

## 2. 现象、根因与被破坏的不变量

### 2.1 现象

`build_diagnostic_factor_targets` 在排序和 `head(top_k)` 之前过滤了未来持有期收益为空或非有限的证券。
因此，当最高分证券没有未来 entry/exit bar 或 realized return，而第 `K+1` 名结果完整时，旧实现会删除
最高分证券并让第 `K+1` 名递补。未来结果是否存在由此改变当期证券、权重、组合收益和成本结论。

### 2.2 根因

候选选择与结果评价共用了同一个 `eligible` DataFrame。它同时包含：

- 当期可知的 `trade_date`、factor；
- 未来才实现的 execution/exit date 和 holding-period return。

先按未来结果过滤再选目标，违反 `as_of → 下一开市日` 与“目标先冻结、结果后评价”的时间边界。

### 2.3 权威不变量

1. 调仓日期只由 test 边界、面板中的独立日期计划和固定 cadence 决定；
2. 候选截面只允许使用 `as_of` 时有限的 factor；
3. 按 `factor * direction` 降序、`symbol` 升序稳定排序，先冻结 exact Top-K；
4. Top-K 冻结后才检查所选证券的 execution、exit 和 return；
5. 任一所选证券结果缺失、非有限、日期不一致或越过 fold，整次稳定 fail-closed；不得删除后递补；
6. 未被选中的证券未来结果缺失或变化不得改变 targets；
7. IC 路径仍可在具有可评价 label 的样本上做描述统计，本包不修改 IC；
8. 历史 immutable artifact 永不回写或重签名。

## 3. 最小复现与通过条件

最小截面为 `A > B > C`、`top_k=2`：

- A 的未来 label 缺失、C 完整：必须拒绝，不能得到 B/C；
- 只有未选中的 C label 缺失：仍得到 A/B，权重不变；
- 任意改变有限未来 label 的数值：证券和权重不变；
- 所选证券的 return 为 null/NaN/Inf，或 execution/exit 缺失、退出早于执行、跨证券不一致、越过 fold：
  稳定拒绝；同日 execution==exit 只用于兼容既有 composite 诊断 fixture，不视为逆序；
- 输入行逆序：同一有效输入仍得到相同 targets。

通过条件：上述反例、既有目标/成本单测和三个直接 runner 邻接测试通过；Ruff、mypy 和 fresh cold import
通过；不运行真实 run，不以本包修复后的代码批量重跑旧候选。

## 4. 历史影响登记

根 canonical 中共有 13 个同时含 `targets.parquet` 与 `portfolio_nav.parquet`、并经过该 helper 或其
composite/model 封装的 M2 诊断 run。对所有受影响 run：

- 无效经济证据：targets、portfolio NAV、gross/net return、Sharpe、drawdown、turnover、费用、
  0.5x/1x/2x 链式收益，以及依赖这些结果生成的机械 research status；
- 仅可保留为描述或保守证伪线索：RankIC、方向、coverage、PIT eligibility/quarantine、redundancy；
- `group_returns.parquet` 同样只来自未来 label 可得的事后截面，不能视为可交易收益；
- 原 artifact 保持不可变；修复后如确需影响探针，只能发布新 run id。

### 4.1 立即 HOLD 的四项既有研究证据

以下 run 的组合/成本通过证据立即标为“待影响审计、不得 promotion”，不能进入 forward、S2 或 PAPER：

1. daily value：`05606a6502cf23f2c3c6cfa69d81147eb2ee8260e99c6e637c7a6ed9741b4015`；
2. MAX：`10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3`；
3. classic composite：`221c1e72fc862ac3d083dee0335471e485aad2eebc2b1ba4e23d7812f131c400`；
4. composite market risk：`4e5cba4577af43c27402e369ca8d2c0d1a6a64cdeb57fb1818cc1c86d662d148`。

第三项的治理结论原本已因预注册“几乎全现金”条件判为 REJECTED，继续保持治理 REJECTED；这里失效的
只是其机械组合/成本结果。第四项是既有 510300 forward source，其前向观察合同同步暂停。R10 volatility
successor 与统一 formal replay 不走本 helper，不扩大判定。

### 4.2 保持不可晋级的九项 REJECTED lineage

以下历史 trial 不因缺陷获得翻案或自动重跑机会，仍保持不可晋级；其中仅靠成本腿形成的拒绝不能再被称为
有效经济证伪：

1. Amihud `25c747ae9d608ab71aaa5a09034b6e0a5f14fa7c3c5209383964df6b7068329c`；
2. 自由流通换手 `2331907e2c0d035488f3ad8841b6cbd1ef3308bd2b80c27b956b90a1f560c1d4`；
3. downside beta `b7d022c3cbe88e6f4462af34095bfcb49d530eb0da7bfbb1fd46e196d4c50c7a`；
4. Alpha158 第四批 `cfbdb09d310eca493b1c867ba1f450cab8d60d67fad4674026d4a84e836c581e`；
5. 第二批 `2ac4c69c80b676d15d7773c90160fa07b7cd222ee054ee9c3bb8b98eedf69b41`；
6. 第三批 `46ffd524ab11bc9d9a44eaa5900b0a55757021a1c682e53e6cd86b433119acd1`；
7. 第一批 `93eda5b79b477c4272d31f39633a0f20599091f536927ab52492bbd94fc8bdc9`；
8. MAX 控制 `30326191600e84cc0c94f9f040ecd5ed0ff9a944e6ed02a183ba5169d7a8e2cf`；
9. LightGBM `a4359202a4a93135cd011fda298bf0eedc64be49c8b8adb542257a5fe77262bb`。

前七项中已有独立 IC、方向、coverage 或冗余失败者，其保守 REJECTED 仍有独立依据。MAX 控制与
LightGBM 的原拒绝主要依赖受污染成本腿，因此只保持“不可晋级”，不把原成本结论继续称为有效证伪。

## 5. 实现与开发检查记录

### 5.1 实现

- 用 test-panel 的日期序列先冻结 cadence，不再从 future-label-valid 行派生日期；
- 每个日期只按 finite factor 与稳定 symbol tie-break 冻结 Top-K；
- 冻结后验证 chosen return、共同 execution/exit date、`exit >= execution` 与 fold 边界；
- 末端没有下一持有期出口的日期作为确定性 horizon boundary 排除；若有效区间内部的 date plan 缺口，
  稳定拒绝；
- 任一 chosen label 或日期无效均在返回 targets 前抛出稳定错误，不递补未选中证券。

### 5.2 运行证据

所有可计检查均使用 Windows 原生 `D:\Miniforge3\python.exe`，唯一前台继承 carrier，BelowNormal、
CPU8—11 (`0xF00`)、数值线程不超过 2。没有真实 run，没有第二研究/测试 Python 实例。

1. 两次后台 carrier 没有返回原生终态，均不计通过证据；随后确认测试 PID、`0xF00` 与临时目录零残留，
   按统筹要求停止该机制；
2. 首次可观测 focused 八文件链：`56 passed, 4 failed`。三项 failure 是新增的严格日期先后检查拒绝
   既有 composite 同日 fixture；一项是 PIT 最末信号没有下一调仓出口，被误当作数据缺失；
3. 最小修正仅允许 `execution == exit` 的既有诊断 fixture，并把连续尾部无出口识别为 horizon boundary；
   仍拒绝 `exit < execution`、跨证券日期不一致、chosen label 缺失/非有限和 fold 越界；
4. 最终 focused 八文件链：`61 passed, 520 warnings in 8.70s`。文件为 evaluator、classic/daily/PIT、
   composite/model 与对应 runner tests；warning 均为既有 Pandera/Polars deprecation；
5. Ruff：改动 source 与 primary test，`All checks passed!`；
6. mypy：`classic_factor_evaluation.py`，`Success: no issues found in 1 source file`；
7. fresh cold import：evaluator、classic/daily/PIT runner、composite/model 均从本 worktree `src` 导入，
   `R11_COLD_IMPORT_PASS`。

提交前 exact4 staged scope、`diff --cached --check`、临时目录和资源零残留核对均通过。安全提交、
integration 合流与 archive-first 退出身份见本记录第 1 节。
