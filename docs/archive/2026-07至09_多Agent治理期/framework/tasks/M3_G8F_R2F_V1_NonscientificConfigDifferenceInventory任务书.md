# M3-G8F-R2F-V1 Nonscientific Config Difference Inventory 任务书

日期：2026-08-28<br>
状态：`FROZEN / TRACKED_ONLY / STATIC_ONLY / CONTRACT_STOP`

## 1. 身份与目标

- task id：`M3-G8F-R2F-V1-NONSCIENTIFIC-CONFIG-DIFFERENCE-INVENTORY`
- exact base / HEAD：`2c2fe86ebd3eba1a77f3728414404dc8e9358ac8`
- branch：`codex/m3-g8f-r2f-v1-nonscientific-config-difference-inventory`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2f-v1-nonscientific-config-difference-inventory`
- 目标：完整重建`config.py` 148个field shapes的selector projection与raw/full hash语义，判断是否存在有业务正当性的non-scientific差异候选，可满足runtime的two distinct raw/full + one shared scientific identity。

本包只做tracked静态审计，不选择字段值、不写config。结论上限`NONSCIENTIFIC_DIFFERENCE_INVENTORY_FROZEN`；
任何候选仍为`USER_CHOICE`，不得写READY。

## 2. exact3 与角色

1. `docs/framework/tasks/M3_G8F_R2F_V1_NonscientificConfigDifferenceInventory任务书.md`（经理唯一写）
2. `docs/framework/deliveries/M3_G8F_R2F_V1_NonscientificConfigDifferenceInventory交付报告.md`（后续唯一审计Worker写）
3. `docs/framework/reviews/M3_G8F_R2F_V1_NonscientificConfigDifferenceInventory独立初验报告.md`（不同reviewer写）

当前只批准路径1。中央复核前不得派Worker/reviewer；不得写config、production、tests、roadmap/governance。

## 3. 权威hash语义

- `raw_config_sha256 = sha256(exact UTF-8 TOML bytes)`；注释/空白可改变raw，但不改变normalized full。
- `full_config_sha256 = sha256(canonical envelope{hash_version,selector="full",config_version,payload=entire normalized document})`。
- `scientific_config_sha256`使用同一envelope，仅payload为field spec selectors包含`scientific`的projection；
  `meta.config_version`不重复进入payload，但进入所有derived identity envelope。
- `canonical_tracking_target_key`独立绑定canonical tracking URI + experiment name，不等于scientific hash。
- runtime `_validate_request`要求两个raw identities、两个full identities、一个scientific identity；因此只改注释/空白无法满足full distinct，必须有至少一个合法normalized non-scientific字段取不同值。

## 4. 完整projection审计矩阵

Worker必须从`_field_specs()`实际148 shapes逐项输出：path、kind、required/literal/range、selector集合、是否进入full/raw/scientific、
对应public consumers及两fold是否另有exact-equality约束。不得只列“看似可变”的少数项。

初始类别冻结如下，须逐项复核而非直接采信：

| 类别 | 代表字段 | scientific关系 | 审计重点 |
|---|---|---|---|
| scientific | data日期/训练最小值、全部walk-forward、features/labels/model/portfolio/backtest/evaluation/costs及部分runtime/provider字段 | 必须两config exact同值 | 任一不同均违反方向A |
| selector-free full-only | `meta.purpose`,`meta.enabled`；Qlib supported_python/url/sha/bytes；G1 rate/retry；`tracking.artifact_root`与log flags | 不进入scientific，但进入full/raw | literal字段不能人为变化；可变字段须证明业务含义与consumer闭包 |
| g1/snapshot/provider-only | `g1_backfill.*`及部分data字段 | 可能不进入scientific或同时进入 | 逐字段核selector；release/config consumers是否要求fold间相等 |
| provider-validation | `validation.provider.*` | 不进入scientific | 是否允许lane-specific验证样本参数，不能仅为制造SHA差异 |
| label-reconciliation | `validation.labels.*` | 不进入scientific | 是否允许lane-specific tolerance，及下游identity影响 |
| acceptance | `acceptance.*` | 不进入scientific | 两fold/aggregate Gate是否要求共享，不能弱化准入来区分hash |
| tracking-target | experiment name/URI | 不进入scientific；另有tracking target identity | 是否可合法按lane区分且与shared artifact root/runtime闭合 |

## 5. 候选准入判据

一个字段只有同时满足以下条件才可进入“业务正当候选”清单：

1. 合法schema字段且不是fixed literal；改变后full与raw均变化、scientific不变。
2. 差异表达真实fold/lane职责，不能是注释、空白、随机串、无意义purpose或人为松紧阈值。
3. 所有其他derived selectors、tracking target、G1/snapshot/provider/validation/acceptance consumers与two-fold aggregate closure继续成立。
4. 不削弱科学口径、数据范围、质量/acceptance Gate、凭据安全、PROJECT-only root或fail-closed语义。
5. 可形成逐字段、逐值、owner明确的future `USER_CHOICE`；当前Worker/reviewer不得代选。

若无字段满足，结论必须为`NO_JUSTIFIED_DIFFERENCE / ARCHITECTURE_REVIEW_CANDIDATE`：登记runtime distinct raw/full要求与
shared scientific要求之间的架构重审候选，但不修改runtime/config。若存在候选，也只能输出排序后的candidate matrix与风险，
保持`CONTRACT_STOP / USER_CHOICE_REQUIRED`。

## 6. 允许与禁止

允许：tracked `config.py`、successor runtime/bridge、直接consumer与已合流R2F task/delivery/review；`rg`、`git show`、
`git ls-files`、`git rev-parse HEAD:<path>`、`Get-Content`、`Get-FileHash`等只读命令。

禁止：Python/pytest/Ruff/mypy/Qlib；读取example的具体值作为正式值；读取LOCKED/ignored/local/真实data；创建config/request/root/evidence；
通过测试fixture推导正式fold/value；修改runtime/schema或stage/commit。

## 7. 强制反例

1. 仅改变TOML注释/空白：raw distinct但full相同，runtime仍拒绝。
2. 改scientific window/model参数：raw/full distinct但scientific也distinct，runtime拒绝。
3. 改fixed literal或添加unknown field：loader拒绝，不能成为候选。
4. 改acceptance/tolerance仅为制造hash：即使技术上non-scientific，也因弱化Gate/无业务依据而不准入。
5. 改tracking experiment/URI：必须证明canonical target、artifact root与两fold消费闭包；不能因“看似lane-specific”自动通过。
6. example或fixture展示两个值：不构成正式SSOT或USER_CHOICE决定。

## 8. Worker交付与review

若中央批准Worker，其delivery必须给出148/148 coverage、按selector分类计数、所有技术候选及逐个consumer证据、
业务正当候选/拒绝理由、剩余USER_CHOICE和是否触发架构重审。独立reviewer至少挑战一个“技术可变但业务不正当”字段，
并复核只改raw不能满足runtime。二者均不得生成值或config。

## 9. 当前静态验收

当前仅本taskbook dirty、cached0、`git diff --check` PASS、UTF-8无BOM、LF-only、TW0、single EOF LF。
终态保持`CONTRACT_STOP`；本包不关闭A13/A14/A16/A19，不运行actual successor/Qlib，也不推进M3 Gate。
