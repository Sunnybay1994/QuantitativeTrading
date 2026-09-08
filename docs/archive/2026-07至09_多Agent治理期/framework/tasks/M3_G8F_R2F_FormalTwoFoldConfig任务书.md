# M3-G8F-R2F Formal Two-Fold Config 任务书

日期：2026-08-28<br>
状态：`FROZEN / STATIC_ONLY / CONTRACT_STOP / USER_CHOICE_REQUIRED`

## 1. 身份与目标

- task id：`M3-G8F-R2F-FORMAL-TWO-FOLD-CONFIG`
- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- branch：`codex/m3-g8f-r2f-formal-two-fold-config`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2f-formal-two-fold-config`
- 目标：只读审计正式双fold配置所需schema/runtime合同，冻结候选tracked路径和待决策矩阵；本包不写配置。

源码能证明fold格式、exact two、config schema和同一tool spec，却不能决定正式科学窗口或业务参数。当前必须
`CONTRACT_STOP / USER_CHOICE_REQUIRED`，不得从example、测试fixture、LOCKED或历史运行推导。

## 2. exact3 与角色

1. `docs/framework/tasks/M3_G8F_R2F_FormalTwoFoldConfig任务书.md`（经理唯一写）
2. `docs/framework/deliveries/M3_G8F_R2F_FormalTwoFoldConfig交付报告.md`（后续唯一审计 Worker 写）
3. `docs/framework/reviews/M3_G8F_R2F_FormalTwoFoldConfig独立初验报告.md`（不同 reviewer 写）

当前只批准路径 1。中央复核前不得派Worker/reviewer，不得创建或修改任何config。

## 3. tracked权威锚点

| 输入 | Git blob / SHA-256 | 用途 |
|---|---|---|
| `src/quant/research/m3/config.py` | `6d60d882...` / `7338ab6a6b959f3a8556bf8011aa6898580df434f920ae167dc8d27f966fedfa` | schema、类型、跨字段约束 |
| `src/quant/research/m3/successor_bridge.py` | `09d8b3b2...` / `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | exact two、fold排序、fresh config/root/tool闭包 |
| `src/quant/research/m3/successor_runtime.py` | `59212daf...` / `272c42f63612e2ce4e927460c1885e95cdab9c17e3d13f52bd82d9734caf608b` | two-fold request与identity |
| `src/quant/research/m3/fetch_qlib_tool.py` | exact HEAD Git blob `b91b63fea7cad3d5866af63ed2afc13524708a12`；working bytes SHA-256 `33342e5f487fab59fd760dd01fcde961df88f04e58e0e73c8a47ca26e59a15c3` | DEFAULT_TARGET_PATH/tool spec SSOT |
| `configs/research/m3_qlib_example.toml` | `74d2caae...` / `fee781d4dab59d2de6fe55eff223cd761b9f7c7f0b87a233da3615e4cddf3892` | 只用于识别字段，禁止提升/复制值 |

## 4. 候选tracked路径与不可变关系

未来配置包候选路径冻结为：

1. `configs/research/m3_successor_fold_001.toml`
2. `configs/research/m3_successor_fold_002.toml`

路径只是候选，不表示获准创建。当前public config schema没有`fold`字段：fold身份只能由future request中的每个fold item
显式绑定`fold`、`config_path`、config raw SHA与full SHA；bridge随后fresh读取该路径并核hash。两项必须按request-side
fold名稳定排序、唯一且exact two，不能把文件名或config内部不存在的字段当作身份。
两配置的完整 scientific projection 必须 exact 相同，明确包括 `data.start_date/end_date`、
`minimum_train_sessions`、全部 `walk_forward` 窗口及全部 model/provider/scientific 字段；fold 不表示不同科学窗口。
runtime仍要求两份raw/full config identity各自不同；该差异只能来自未来owner逐字段批准且不进入scientific projection
的字段，当前不得猜字段、添加无意义值或为制造SHA差异改变字节。Qlib tool与tracking合同仍须闭合；
`build_qlib_dump_tool_spec`结果必须exact相等。两者`tracking.artifact_root`必须为同一个待中央冻结的PROJECT-relative
literal，并经public `project_stage_root`解析为同一exact controlled root；当前该literal为`CENTRAL_RESOURCE / MISSING`。

## 5. 决策矩阵

| 字段组 | 当前证据 | 状态 / 决策主体 |
|---|---|---|
| fold ids | regex只证明`fold_[0-9]{3}`形状、distinct、sorted、exact two；`fold_001`,`fold_002`仅为测试/路径候选 | `USER_CHOICE`：正式request/config owner确认；不能由fixture或文件名升级 |
| dataset start/end、universe/source | schema已知，无正式本轮SSOT值；两config必须取exact同值 | `USER_CHOICE`：研究/用户冻结 |
| minimum_train_sessions | 正整数且与train交叉约束；example值不可采用 | `USER_CHOICE` |
| train/validation/test/step/embargo windows | 类型与`step>=test`、`train>=minimum`、embargo覆盖最大horizon可验证；业务值无SSOT；两config exact同值 | `USER_CHOICE` |
| horizons/fold date boundaries | runtime支持两fold/h5+h10合同，但fold不是不同scientific window；正式共同window仍不存在 | `USER_CHOICE` |
| model/provider/scientific参数 | config schema可列字段，无正式选择证据；两config完整scientific projection exact同值 | `USER_CHOICE` |
| non-scientific raw/full差异 | runtime要求两个raw identity和两个full identity，但当前无获批差异字段/值 | `USER_CHOICE`：owner逐字段批准；不得猜或造无意义差异 |
| Qlib version/tool path/bytes | target `0.9.7`；tracked dump `data/external/qlib/v0.9.7/dump_bin.py`, size21847, SHA `b8f34c57...` | 文件侧`AVAILABLE_VERIFIED`；双config spec仍`MISSING` |
| tracking.artifact_root | 两配置必须同literal并解析到future controlled root | `CENTRAL_RESOURCE` |
| raw bytes/full SHA | 文件尚未创建 | `MISSING`；参数全部批准后由单一config Worker生成 |

## 6. 后续配置包合同（当前未授权）

只有用户/研究owner逐字段确认科学窗口、业务参数与两个正式request-side fold id，中央冻结artifact root后，才可另行批准唯一Worker写两份候选config及delivery；
必须使用`config.py`现有schema，不新增键、不复制example整文件、不读LOCKED/local config。两文件需记录raw bytes、SHA-256、
public loader结果、scientific projection exact equality、获批non-scientific差异矩阵和tool spec exact equality；future request再逐项绑定fold id→config path/raw/full SHA。
任一未决字段不得用默认值补齐，也不得向config虚构fold字段。

## 7. 对抗与失败语义

- example能通过loader或dump SHA正确，仍不得成为formal config。
- 两份config存在，但future request没有逐项绑定fold id→config path/raw/full SHA，或绑定少/多/重/乱序，拒绝。
- config内新增未经schema批准的`fold`字段，或只凭候选文件名推断fold身份，拒绝。
- 两config任一scientific字段（包括日期或walk-forward窗口）不同，拒绝；不得把fold解释成不同科学窗口。
- 两config raw/full identity相同，或差异来自未获批/无意义non-scientific值，均拒绝。
- tool spec、artifact_root、共享科学参数发生非批准漂移，拒绝。
- fold窗口重叠、step/test/embargo/minimum约束失败，拒绝；不得通过改loader放宽。
- 候选值来自测试fixture、LOCKED retained、ignored/local文件或历史运行，`SCOPE_STOP`。
- 缺任何业务值时稳定终态`CONTRACT_STOP / USER_CHOICE_REQUIRED`，不写半成品config。

## 8. 静态验收与边界

任务书阶段仅本文件dirty、cached0、`git diff --check` PASS、UTF-8无BOM、LF-only、TW0、single EOF LF。
本包不关闭A13/A14/A16/A19，不创建request/root，不运行Python/Qlib，不声称actual successor或M3 Gate完成。

## 9. TRACKED_CONTRACT_CONFLICT 与中央方向A重冻

首轮审计发现：原§4允许“经批准的window身份字段”不同，但`config.py`将data日期、minimum train和全部
walk-forward字段纳入scientific projection；`successor_runtime._validate_request`同时要求raw identities count=2、
full identities count=2、scientific identities count=1。该原表述会让runtime稳定拒绝，Worker因此以
`TRACKED_CONTRACT_CONFLICT` STOP，证据永久保留在delivery。

中央裁定保持现有runtime/config SSOT：两config完整scientific projection exact相同；fold/lane仅由future request
item的fold + config path/raw/full SHA、各自G1 release与运行lane闭包表达；raw/full所需差异只能来自未来明确批准的
non-scientific字段和值。当前所有正式科学值、fold ids、non-scientific差异与controlled artifact root仍未决，故重冻后
上限仍为`FORMAL_CONFIG_CONTRACT_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`，不得创建config或宣称READY。

## 10. REVIEW_FAIL1 Git identity修正

首轮独立初验确认方向A合同成立，但发现`fetch_qlib_tool.py`的working-tree `git hash-object`结果
`608f35238858cc054d0f3ecb444f7cd73177f332`被误标为HEAD Git blob。exact HEAD blob为
`b91b63fea7cad3d5866af63ed2afc13524708a12`；working bytes SHA-256、tool path/size/content结论不变。
其余四个表列blob经`git rev-parse HEAD:<path>`复核均正确。原Worker仅同步delivery，原reviewer复验；不得借此改变方向A、
USER_CHOICE矩阵或任何config/runtime字节。
