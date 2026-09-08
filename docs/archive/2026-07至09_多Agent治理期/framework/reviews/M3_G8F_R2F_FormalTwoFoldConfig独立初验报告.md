# M3-G8F-R2F Formal Two-Fold Config 独立初验报告

日期：2026-08-28<br>
状态：`REVIEW_PASS / STATIC_ONLY / CONTRACT_STOP / USER_CHOICE_REQUIRED`

## 1. 审查身份与边界

- task id：`M3-G8F-R2F-FORMAL-TWO-FOLD-CONFIG`
- exact base / HEAD：`10af1582845fbffd8356fa987d0c5ce2d6783ed4`
- REWORK2 taskbook SHA-256：`fce6519f51de605e5a3aff21ecc5fda5b312165a9a16ff86bddd5ff22146c8ef`
- REWORK2 delivery SHA-256：`8b752f7e1c6d6746aca3c71c2277125b467596b646de2267c96568b152cbeb17`
- reviewer 与审计 Worker 角色分离；本轮唯一写路径为本报告。

本轮仅读取 taskbook、delivery 与任务列明的 tracked 源码，使用 Git、`rg`、
`Get-FileHash`与定向文本/字节检查。未运行 Python/Qlib，未读取 example 配置值、LOCKED、
ignored/local 或真实 data，未创建 config、request 或 root。

## 2. REVIEW_FAIL1 与 REWORK2 复验

### F1 — tracked Git blob 锚点失实（已闭合）

首轮任务书 §3 和交付报告 §2 都把 `src/quant/research/m3/fetch_qlib_tool.py` 的 Git blob
误记为 `608f35238858cc054d0f3ecb444f7cd73177f332`，因而首轮初验正确给出 `REVIEW_FAIL`。
REWORK2 独立复核得到：

- `git rev-parse HEAD:src/quant/research/m3/fetch_qlib_tool.py`：
  `b91b63fea7cad3d5866af63ed2afc13524708a12`；
- `git ls-files -s -- src/quant/research/m3/fetch_qlib_tool.py` 也返回
  `b91b63fea7cad3d5866af63ed2afc13524708a12`；
- `git cat-file -e 608f35238858cc054d0f3ecb444f7cd73177f332^{blob}` 退出 `128`，该 ID 不是当前
  Git 对象库中的 blob；它只是历史 working-tree `git hash-object -- <path>` 结果；
- working-file SHA-256 仍为文档所记的
  `33342e5f487fab59fd760dd01fcde961df88f04e58e0e73c8a47ca26e59a15c3`，不能用它弥补 Git blob
  字段的错误。

更新 taskbook §3/§10 与 delivery §2/§7 已把 exact HEAD Git blob 更正为 `b91b63...`，
并精确保留 `608f3523...` 的历史性质。其余四个表列路径经
`git rev-parse HEAD:<path>` / `git ls-files -s` 复核均与文档一致：

- `config.py`：`6d60d8827a803453bb26868208929d3c31960dbd`；
- `successor_bridge.py`：`09d8b3b267ea30fc0764d5734d4636722f5ed22b`；
- `successor_runtime.py`：`59212daf87a3b8f44052e27f1a68abe1cef8f5c9`；
- `m3_qlib_example.toml`：`74d2caae67fc0ec86669fd25f6d973e521405c87`。

F1 已闭合，且本返工仅修正证据标签；working bytes SHA-256、tool path/size/content 结论、
中央方向 A、USER_CHOICE 矩阵与 config/runtime 合同均无语义漂移。

## 3. 原冲突与方向 A 复核

| 合同 | 独立 tracked 证据 | 结论 |
|---|---|---|
| 原 window 差异冲突 | `config.py` 将 `data.start_date/end_date`、`minimum_train_sessions`、五个 `walk_forward.*_sessions` 以及 model/provider/scientific 字段纳入 `scientific` selector；`_project` 按 selector 生成投影。`successor_runtime._validate_request` 要求 raw identity=2、full identity=2、scientific identity=1。 | 原允许两 fold 使用不同 scientific window 的表述必然被 runtime 拒绝；原 Worker `TRACKED_CONTRACT_CONFLICT` STOP 证据正确。 |
| 方向 A | 更新 taskbook §4/§9 要求两 config 的完整 scientific projection exact 相同，明确包含日期、minimum train、全部 walk-forward、model、provider 与 scientific 字段。 | 与当前 config/runtime SSOT 一致；原冲突被重冻结 supersede，但历史在 taskbook §9 和 delivery §3.3 中得到保留。 |
| distinct raw/full | runtime 明确要求两个 raw 和两个 full identity；full hash 覆盖完整规范化文档，raw hash 覆盖文件字节。 | 差异只能来自未来 owner 明确逐字段批准、且不进入 scientific projection 的字段和精确值；当前不存在可由 Worker 猜测的合法值。 |

## 4. fold/request 身份与候选路径

- `successor_bridge.py` 的 fold item 分别携带 `fold`、`config_path`、raw/full config SHA 与 G1
  release 身份；`_parse_fold` fresh 读取指定配置并校验两个 SHA。
- bridge 只冻结 `^fold_[0-9]{3}$`、exact two、distinct 和 sorted；源码没有把正式名称指定为
  `fold_001`/`fold_002`。
- `two_fold_identity` 绑定 request-side fold、config relative path、raw/full SHA、G1 release id 与
  manifest SHA；终端 fold binding 还闭合 release root、snapshot、experiment、work 与 receipts。
- `config.py` 中没有 `fold` 字段，未知键以 `UNKNOWN_KEY` fail closed。因此 fold 身份不能从
  config 内部伪造，也不能从文件名推断。
- `git ls-files` 对两个候选 config 路径无输出，精确 `Test-Path` 也均为 `False`。候选名和路径
  不是 SSOT，仍需 future request/config owner 与中央精确冻结。

## 5. reviewer 新增对抗反例

1. 两份 config 只差一个日期或 walk-forward 数值：该字段进入 scientific projection，
   scientific identity 数量变为 2，runtime 拒绝。
2. 复制同一 config 字节到两路径：即使 fold id 不同，raw/full identity 数量仍为 1，
   runtime 拒绝。
3. 为制造 raw/full 差异任意改动 non-scientific 值：技术上可能改变 hash，但当前没有 owner
   对“哪个字段+什么精确值”的批准，因而仍是 `USER_CHOICE_REQUIRED`，不得生成 config。
4. 仅创建候选文件名或在 config 中新增 `fold`：前者缺 request-side 绑定，后者触发
   `UNKNOWN_KEY`；均不能建立正式 fold/lane 身份。

## 6. 范围与字节卫生

- REWORK2 审查前 worktree 仅 taskbook、delivery 和原 review 三个 untracked 文档，cached count=0，
  五个 tracked 锚点路径均无 diff。
- taskbook、delivery 和 review 均为 UTF-8 无 BOM、NUL0、CRLF0、bare CR0、TW0、single EOF LF；
  `git diff --check` PASS。
- 本 reviewer 未读取 example 值，未查找 parent/sibling/latest fallback，未读取任何 LOCKED、
  ignored/local 或真实 data。

## 7. 初验结论

方向 A 的重冻结合同在语义上与当前 tracked config/runtime/bridge 一致，且正确保留了
原 `TRACKED_CONTRACT_CONFLICT` STOP 和 `REVIEW_FAIL1` 历史。F1 精确 Git 身份错误已由经理与同一 Worker
在各自原文档中最小修正，且未改动源码、配置或冻结语义。本轮结论为 `REVIEW_PASS`。

无论 F1 返工前后，当前结论上限始终是：

`FORMAL_CONFIG_CONTRACT_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`

正式 fold ids、正式 config 路径、全部科学/业务值、获批 non-scientific 差异字段及精确值、
controlled artifact root 仍未决。不得声称 config ready，不得创建 config/request/root，不关闭
A13/A14/A16/A19，不表示 actual successor、Qlib 或 M3 Gate 推进。
