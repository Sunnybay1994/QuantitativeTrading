# M3-G8F-R2F Formal Two-Fold Config 交付报告

日期：2026-08-28<br>
状态：`DELIVERED / FORMAL_CONFIG_CONTRACT_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`

## 1. 交付范围

- task id：`M3-G8F-R2F-FORMAL-TWO-FOLD-CONFIG`
- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- 首轮审计 taskbook SHA-256：`6ecb54cdb5bba0ce9976748d065a349865128ce117ffebdb2928f98883c06fb6`
- 当前 REWORK2 taskbook SHA-256：`fce6519f51de605e5a3aff21ecc5fda5b312165a9a16ff86bddd5ff22146c8ef`
- 唯一写路径：`docs/framework/deliveries/M3_G8F_R2F_FormalTwoFoldConfig交付报告.md`
- 审计类型：tracked-only `STATIC_ONLY / CPU NONE`。

本轮仅用 Git 对象、tracked 源文件、`Get-FileHash`、`Get-Item`、`rg`与定向文本读取复核配置 schema、bridge、runtime 与 tool 合同。未运行 Python/Qlib，未读取 LOCKED、ignored/local 或真实 data，未写任何 config、production、test、taskbook 或 review。

## 2. tracked 锚点复核

| 路径 | Git blob | working SHA-256 | 结果 |
|---|---|---|---|
| `src/quant/research/m3/config.py` | `6d60d8827a803453bb26868208929d3c31960dbd` | `7338ab6a6b959f3a8556bf8011aa6898580df434f920ae167dc8d27f966fedfa` | 与 taskbook 一致 |
| `src/quant/research/m3/successor_bridge.py` | `09d8b3b267ea30fc0764d5734d4636722f5ed22b` | `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | 与 taskbook 一致 |
| `src/quant/research/m3/successor_runtime.py` | `59212daf87a3b8f44052e27f1a68abe1cef8f5c9` | `272c42f63612e2ce4e927460c1885e95cdab9c17e3d13f52bd82d9734caf608b` | 与 taskbook 一致 |
| `src/quant/research/m3/fetch_qlib_tool.py` | `b91b63fea7cad3d5866af63ed2afc13524708a12` | `33342e5f487fab59fd760dd01fcde961df88f04e58e0e73c8a47ca26e59a15c3` | exact `HEAD:<path>` blob；working bytes SHA 不变 |
| `configs/research/m3_qlib_example.toml` | `74d2caae67fc0ec86669fd25f6d973e521405c87` | `fee781d4dab59d2de6fe55eff223cd761b9f7c7f0b87a233da3615e4cddf3892` | 只确认 tracked 身份，未读取或采用其值 |

tracked config 目录中与 M3 直接匹配的文件仍只有 `configs/research/m3_qlib_example.toml`。两个候选 formal config 路径当前不存在，也未获准创建。

REVIEW_FAIL1 证据指出，首轮表中将 working-tree `git hash-object`
`608f35238858cc054d0f3ecb444f7cd73177f332` 误标为 HEAD Git blob。该值仅作为历史 working-tree
hash-object 结果保留，不再表述为 Git 库对象身份。

## 3. public config / request 合同审计

### 3.1 fold 是 request-side identity

- `config.py` 的 148 个允许 shape 中没有 `fold` 字段；未知键由 `UNKNOWN_KEY` fail closed。
- `successor_bridge.py` 的 `_FOLD_KEYS` 明确分离 `fold`、`config_path`、`config_raw_sha256`、`config_full_sha256`。`_parse_fold` fresh 读取 config，并同时核对 raw/full SHA。
- fold regex 只是 `^fold_[0-9]{3}$`；bridge 和 runtime 只要求 exact two、distinct、sorted。没有 tracked 合同把正式名称限定为 `fold_001` 与 `fold_002`。
- `two_fold_identity` 把每项 request-side fold、config relative path、raw/full config SHA 与 G1 release identity 一起绑定。因此候选文件名不能替代 request 绑定。

结论：taskbook 修正后的 request-side fold 语义与 public 合同一致；`fold_001`/`fold_002` 和两个 config 路径仍只是候选，状态必须保持 `USER_CHOICE`。

### 3.2 config 必须 fresh 闭合

- loader 严格校验 UTF-8 TOML、148 个 field shape、必需键、未知键、类型与跨字段关系；不允许用自定义 `fold` 字段补身份。
- `data.start_date/end_date`、`minimum_train_sessions`、walk-forward 五个 session 字段与 model/provider/science 字段都进入 `scientific` 投影。
- 跨字段规则包括：`start<=end`、embargo 覆盖最大 horizon、`step>=test`、`train>=minimum_train_sessions`。
- `tracking.artifact_root` 必须是安全的 project-relative POSIX path；bridge 要求两份 config 解析到同一已存在 controlled root。

### 3.3 历史发现：window 差异与 runtime scientific identity 冲突

`successor_runtime._validate_request` 同时要求：

1. 两 fold 的 `raw_config_sha256` 有两个不同值；
2. 两 fold 的 `full_config_sha256` 有两个不同值；
3. 两 fold 的 `scientific_config_sha256` 只有一个共享值。

源码注释明确解释：summary/work 按 scientific projection join folds，full/raw identity 则每个 lane 各自不同。但 taskbook §4 当前允许两份 config 的“经批准的 window 身份字段”不同；而 `data.start_date/end_date` 和所有 `walk_forward.*` 都属于 `scientific` 投影。若实现者按该表述生成不同 window 值，runtime 会稳定拒绝请求。

这是首轮审计发现的 tracked 合同冲突，当时本 Worker 正确 STOP 且未做架构选择。原冲突证据保留如下：

- 保持现有 runtime SSOT：两 config 的全部 scientific 投影（含 window）必须 exact 相同，fold 差异仅由 request/release/lane identity 及获准的非 scientific 配置字节体现；或
- 如果业务确实要求每 fold 不同 scientific window，则需另立 public runtime/schema 架构变更包，不能由本 config 包私自放宽。

中央已选择方向 A，并由经理在 taskbook SHA-256
`2bcdb2d27e7292896b3ffab8849cdc45615deaaa702d8995f7eb261c93adbd1b` 中完成 supersession：

- 保持现有 runtime/config SSOT；
- 两份 future config 的完整 scientific projection 必须 exact 相同，包括全部日期、window、model、provider 与 scientific 字段；
- fold/lane 只由 request-side fold + config path/raw/full SHA、各自 G1 release 与运行 lane 表达，不表示不同 scientific window；
- runtime 需要的两个 distinct raw/full identity 只能来自未来 owner 逐字段明确批准、且不进入 scientific projection 的字段/值。当前这些字段/值仍是 `USER_CHOICE`，不得猜测、添加无意义值或为制造 SHA 差异改字节。

因此原 `TRACKED_CONTRACT_CONFLICT` 已被方向 A 权威重冻结 supersede，但 USER_CHOICE 与资源缺口尚未解决；当前仍不得生成两份 formal config。

## 4. Qlib tool 闭合

- `DEFAULT_TARGET_PATH` 的唯一 tracked SSOT 为 `data/external/qlib/v0.9.7/dump_bin.py`。
- `config.py` 冻结 Qlib `0.9.7`、dump bytes `21847`、SHA-256 `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f`。
- tracked dump 实际文件大小为 `21847`，实测 SHA-256 为 `b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f`。
- bridge 要求 tool path 精确等于 `DEFAULT_TARGET_PATH`，两 config 的 `build_qlib_dump_tool_spec` 结果 exact 相等，并 fresh 闭合 tracked bytes/size/SHA。

结论：文件侧 tool 为 `AVAILABLE_VERIFIED`；尚未存在的两份 formal config 中 tool spec 仍为 `MISSING`。本轮未运行 downloader、Qlib 或 Python。

## 5. USER_CHOICE / resource 矩阵

| 项 | 复核结论 | 状态 / 唯一决策主体 |
|---|---|---|
| formal fold ids | 只有 regex、exact-two、distinct、sorted 合同；无 exact 名称 SSOT | `USER_CHOICE`：request/config owner；候选名不得升级 |
| formal config paths | 两路径只是候选，当前不存在 | `USER_CHOICE` + 中央 exact-path 冻结 |
| dataset start/end、universe/source | schema/固定 literal 范围可验，本轮正式时窗无 SSOT | `USER_CHOICE`：用户/研究 owner |
| minimum train 与 walk-forward 窗口 | 类型/跨字段规则存在，业务值无 SSOT；方向 A 要求两 config exact 同值 | `USER_CHOICE`：研究 owner 逐字段冻结 |
| fold date boundaries / horizons | runtime horizon 合同存在，formal split 无 SSOT | `USER_CHOICE`：研究 owner；不得从 fixture 推导 |
| model/provider/scientific 参数 | schema 可验，正式值无 SSOT | `USER_CHOICE`：研究 owner |
| tracking artifact root | 两 config 必须同 literal，并解析到同 controlled root | `CENTRAL_RESOURCE / MISSING` |
| raw/full SHA | config 未创建；runtime 要求两 lane 各自 distinct | `MISSING`：参数与合同重冻结后由唯一 config Worker 生成 |
| scientific SHA | runtime 要求两 lane exact 相同，中央方向 A 已重冻结 | `REQUIRED_CONTRACT / FROZEN`：所有 scientific 字段 exact 同值 |
| non-scientific raw/full 差异 | runtime 要求两 raw/full identity distinct，但当前无获批差异字段/值 | `USER_CHOICE`：owner 逐字段批准，不得猜测或造无意义差异 |
| dump tool | tracked path/bytes/SHA 闭合 | 文件侧 `AVAILABLE_VERIFIED`；config 侧 `MISSING` |

## 6. 对抗核对

- config 新增 `fold` 键：由 strict schema 以 `UNKNOWN_KEY` 拒绝。
- 仅凭文件名推断 fold：不满足 request item 的 fold/path/raw/full SHA 绑定，拒绝。
- fold 少/多/重/乱序或不匹配 regex：bridge 在 config/release I/O 前拒绝。
- 两 config raw/full identity 相同，runtime 拒绝；scientific identity 不同，runtime 同样拒绝。
- tool spec/path/size/SHA 任一漂移：bridge fresh 校验拒绝。
- artifact root 不同、不存在、不是 project member 或不等于 controlled root：bridge 拒绝。
- example/test/LOCKED/ignored/local/历史运行提供候选值：本轮未读取或采用；合同要求 `SCOPE_STOP`。

## 7. REWORK2 Git identity 纠正

按更新 taskbook 和 REVIEW_FAIL1 重新用三种独立口径核对
`src/quant/research/m3/fetch_qlib_tool.py`：

- `git rev-parse HEAD:src/quant/research/m3/fetch_qlib_tool.py`：
  `b91b63fea7cad3d5866af63ed2afc13524708a12`；
- working-tree `git hash-object -- <path>`：
  `608f35238858cc054d0f3ecb444f7cd73177f332`；
- working bytes SHA-256：
  `33342e5f487fab59fd760dd01fcde961df88f04e58e0e73c8a47ca26e59a15c3`。

其余四个表列 blob 已由独立初验和更新 taskbook 确认正确。本纠正只修复 Git 身份证据标签；tool path/size/content/SHA 结论、中央方向 A、USER_CHOICE 矩阵和 config/runtime 合同全部不变。

## 8. 验收结论与未决边界

静态审计证明 taskbook 对 request-side fold 绑定的纠正是正确的，tool 文件侧也已闭合。首轮发现的 scientific window 冲突已被中央方向 A 和更新 taskbook 权威 supersede：两 config 必须共享 exact scientific projection。但正式 fold ids、正式 config 路径、全部科学/业务值、用于产生 distinct raw/full identity 的获批 non-scientific 差异，以及 controlled artifact root 仍未决。

因此稳定终态为：

`FORMAL_CONFIG_CONTRACT_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`

本交付不关闭 A13/A14/A16/A19，不表示 config ready，不允许创建request/root/CLI，不表示 actual successor、Qlib 或 M3 Gate 完成。下一步必须由独立 reviewer 复核 supersession、完整 scientific equality、distinct raw/full 的未决 non-scientific 来源及其余 USER_CHOICE 边界。
