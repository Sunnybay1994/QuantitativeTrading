# M3 G1 R1B / R1C-A 主验返工任务单

日期：2026-07-16  
状态：**待外部实现 → 全新外部独立初验**  
模型：实现与独立初验均使用非 fast `cursor-grok-4.5-high`；必须是不同新上下文  
前置证据：[`M3_G1_R1B_R1C-A主Agent终验报告.md`](M3_G1_R1B_R1C-A主Agent终验报告.md)

## 1. 目标与白名单

只关闭主验报告 P0-A、P0-B、P1-C、P1-D，不启动 R1C-B，不改变上游算法、配置数值或 M4-C0。

允许修改：

```text
src/quant/research/m3/g1_workflow.py
src/quant/research/m3/run_g1.py
tests/unit/test_m3_g1_workflow.py
tests/unit/test_m3_run_g1.py
docs/agent/M3_G1_R1B_R1C-A主验返工交付报告.md
docs/agent/M3_G1_R1B_R1C-A主验返工独立初验报告.md
```

除非公共导出实际变化，否则不得修改 `__init__.py`。不得修改 README、路线图、configs、data/artifacts、M4 文件、既有报告或任务书。默认不联网、不读取 token、不访问 archive/data legacy。

## 2. F1：补齐 `VerifiedG1WorkflowStateV1` 自证

### 现象 / 根因

详见主验 P0-A。当前可构造 HISTORY 已完成但 candidate/responses/counts 为空的 `Verified*` 对象。

### 必须满足的规则

在 `__post_init__` 内对任务书 §7、§9.2 做 exact-type、全量双向闭包校验；不能只校验“有阶段时有对象”，还要拒绝“无阶段却提前出现对象”：

- INDEX 未完成：index responses 为空，derived/history/reference/candidate/prepared/published 全为空，history/reference counts 和 history symbols 为 0。
- INDEX 完成：index responses 与 static index plan totals/keys 一致，derived plan 必须存在，counts 等于 verified plan totals。
- HISTORY 完成：history responses 与 derived plan 精确闭包，candidate 必须存在；未完成时不得提前出现 candidate/reference/prepared/published。
- REFERENCE 完成：reference responses 与 candidate 派生计划精确闭包；未完成时不得提前出现 prepared/published。
- PREPARE 完成：prepared 必须存在且与 candidate/build inputs 一致；普通 REFERENCE state 不得携带 prepared。
- PUBLISH 完成：published 与 prepared 必须同时存在并逐字段一致；未完成时 published 必须为空。
- `counts` 永远是当前 verified plan totals，不是 receipt 已完成数；集合必须 exact tuple、稳定顺序、无重复。

值对象失败只抛稳定 `ValueError`，不得泄露对象 repr、路径或底层异常。不要在 `__post_init__` 做 IO、联网或扫描目录。

### 新增测试

至少用 `dataclasses.replace(valid_state, ...)` 覆盖：

1. HISTORY completed + candidate None / history responses 空；
2. 无 HISTORY 却提前 candidate；
3. 无 PREPARE 却提前 prepared；
4. 无 PUBLISH 却提前 published；
5. counts 与 plan totals 不一致；
6. response 缺项、重复、乱序；
7. 每个真实合法阶段 state 仍能构造，避免过严误拒。

## 3. F2：补齐 `G1CliResultV1` 自证

### 必须满足的规则

- `primary_candidate_key`、`release_id`、`manifest_sha256` 非空时必须是小写裸 64 hex；bool/子类/任意字符串拒绝。
- identity 生命周期严格按 R1C 任务书 §6.1 双向校验：HISTORY 前全空；HISTORY/REFERENCE 只有 candidate key；显式 PREPARE 才出现 release ID；PUBLISH 才出现 manifest；不得提前或缺失。
- FAILED / SUCCESS / INCOMPLETE、command、error_code、error_operation 形成闭包：workflow code 必须有合法 Operation；CLI-only code 不得伪造 workflow operation；非 FAILED 无 error 字段。
- counts/stages 保持既有规则；不得为通过测试放宽到任意 Mapping 或 `strict=False`。

### 新增测试

逐字段覆盖非法 hex（长度、大小写、非 hex）、三个 identity 提前/缺失、非法 `error_operation`、workflow error 无 operation、CLI-only error 携带 operation，以及合法 HISTORY/REFERENCE/PREPARE/PUBLISH/FAILED 样例。

## 4. F3：项目内 config 路径闭包

把内部配置加载边界改为显式接收 `project_root`。必须证明：

1. 用户提供的 config 是项目根内普通 `.toml` 文件；项目外绝对/相对穿越均拒绝；
2. config 本身和从项目根到 config 的现有祖先均非 symlink/reparse 路径；
3. 读取前后文件物理身份、size/mtime/bytes identity 不变，TOCTOU fail closed；
4. 所有失败映射 `CLI_CONFIG_INVALID`/exit 2，stdout/stderr 不含路径、token、异常 cause/traceback；
5. 不限制必须位于 `configs/research/`，任务书只冻结“项目内普通 TOML”，不要擅自收窄业务布局。

新增：项目外合法 TOML、`..` 穿越、末端 symlink、祖先 symlink、读取中替换、合法项目内配置测试。

## 5. F4：argparse 后保留已识别 command

实现一个仅用于错误归属的安全 command 识别步骤；必须正确跳过 `--config`/`--project-root` 的参数值，不得把路径名中的 `status` 等误认成 command。

- 没有或未知 command：`command=None`。
- 已无歧义出现一个合法 command，随后未知 option/缺 option value/禁止参数失败：保留该 command literal。
- 多 command、command 出现在 option value、未知 subcommand：不得猜测。

修正现有 `test_argparse_rejects_token_and_unknown` 中与任务书冲突的统一 `None` 期望，并增加上述反例。

## 6. P2 可选加固：stdout 写失败

不阻断本次返工通过。若实现，范围仅限 `run_g1.py` 和对应测试：规范 JSON 加换行尽量单次 write；写/flush 异常不向上传播 traceback，返回 2 并 best-effort 写稳定 stderr；一旦 stdout 可能部分写入，不在同一流追加第二份假 JSON。不得声称物理管道中断时仍能保证完整一行。

## 7. 禁止项

- 不修改 taskbook 来迁就现有实现；不把 `Verified*` 改名规避自证。
- 不新增 IO 到值对象构造器，不扫描 data/release，不调用 connector。
- 不用 `assert` 代替生产校验，不接受 dict/duck type，不用 `strict=False`。
- 不修改 M4-C0 或共享配置；若并行会话触碰本白名单文件，立即停止并协调串行。
- 不启动真实 Tushare/BaoStock，不读取本地 token，不更新 Gate/路线图。

## 8. 实现验证

先运行新增自证/路径/argparse 定向测试，再运行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest tests/unit/test_m3_g1_workflow.py tests/unit/test_m3_run_g1.py -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

五段 fake 长测可在包级实现时保留原有通过证据；独立初验必须在 M4-C0 停止写入后运行一次全量 `python -m pytest -q`。若耗时长，使用长等待间隔，不重复启动并行全量 pytest。

交付报告状态写“待独立初验”，逐项映射 F1–F4；不宣称 R1B/R1C/Gate 通过。

## 9. 独立初验（全新 Grok High）

除固定初验报告外只读。必须增加实现者未使用的对抗：

1. 对每个合法阶段 state 做一处“整体自洽但阶段提前/滞后”的替换，证明 `VerifiedG1WorkflowStateV1` 双向闭包；
2. CLI PREPARE 用合法 candidate/release hex 但错误 manifest 出现，PUBLISH 缺 manifest，均须拒绝；
3. config 末端是普通文件但中间目录 symlink 到项目外，须 `CLI_CONFIG_INVALID` 且零路径泄露；
4. argv 的 config 路径值恰为 `status`、随后真实 command 为 `history` 且未知 option，错误归属必须是 `history`；
5. 复查生产路径无新增网络、目录扫描、token、`os.replace`，M4-C0 文件未被修改。

初验失败按“现象—根因—规则—最小复现—新增测试—通过条件”退回实现，直至通过后再交主 Agent 复验。
