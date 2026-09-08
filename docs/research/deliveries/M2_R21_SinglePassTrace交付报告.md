# M2-R21-SINGLE-PASS-TRACE 交付报告

## 结论

`DELIVERY_READY`（Windows fixture-only implementation validation complete）。

本交付只实现任务书 §5.1 / §8 批准的 SinglePassTrace factor 包，不实现 runner 接入，
不改变 ETF 链，也不构造 receipt、label、evaluate、publish 或经济执行路径。

## 实现与文件范围

本次 exact3 改动为：

1. `src/quant/factors/classic_eleventh_batch.py`
   - 保留原 `compute_eleventh_batch_daily_factors(bars, *, sessions)` 签名、三列结果、实际 bar keys、排序、
     正零归一、输入校验和错误顺序。
   - 抽出共享计算 core；旧入口和新入口各自只经过一次特征构造、一次公共
     `rank_cross_sectional_components` 调用和一次六期相关统计。
   - 新增 `compute_eleventh_batch_daily_factors_with_trace`，在同一 grid/ranked/correlation 中间关系上投影
     `factors`、`component_counts`、`observations` 三张表；完整 session grid 的无 bar 行不会进入 factors。
   - component 计数、lag/session flags、rank member flags、window/pair、两侧 ss 与 primary reason 均由同次中间关系投影。
   - 新入口返回前执行 schema、键/排序、有限性、window、rank、方差与最终因子一致性检查；trace-only 不可解释状态
     fail closed 且不返回 partial mapping，旧入口不执行该诊断拒绝。
2. `tests/unit/test_classic_eleventh_batch.py`
   - 增加三表 exact schema/order/dtype、旧新因子恒等、single rank call、完整 grid/no-bar、warmup/lag/gap、
     zero-volume、single-member/all-tie、variance reason、输入拒绝和无 bar ss 故障注入覆盖。
   - 保留既有独立手算 Pearson、rank、正零、gap、负 volume、nonfinite、schema 与配置 oracle；未以共享 core
     自比较替代独立预期。
3. `docs/research/deliveries/M2_R21_SinglePassTrace交付报告.md`
   - 本报告。

未修改 taskbook、roadmap、runner、receipt、labels、rank helper、config、schema、evaluator、`__init__.py` 或 ETF 链。

## 合同与负例映射

- `factors` 仅为 `symbol/String`、`trade_date/Date`、`alpha101_002/Float64`，键来自实际 bars；新旧入口逐值、null、
  排序和正零一致。
- `component_counts` 固定两 component、按 `trade_date/component` 排序；`grid_symbols` 是输入 symbols × sessions，
  `finite_values` 来自 long-form，`ranked_values` 来自同次公共 rank，n<2 时为 0。
- `observations` 覆盖 symbols × 完整 sessions；index 0/1 的 lag 为 null，index<5 的 `window_ready=false/pair_count=null`，
  index 5/6 仍为八期 warmup；缺 bar 不压缩窗口；lag1 volume=0 不额外过滤；ss 不 clamp。
- 当前缺 bar 优先于 warmup，随后按 warmup、pair、双侧/volume/return 非正方差、VALID 的顺序生成 `primary_reason`。
  VALID 与当前 bar 存在且最终因子非 null/finite 严格等价。
- 覆盖缺 bar 的 lag1/lag2 与 pair incomplete、组件单成员 rank null、n>=2 全 tie 仍有有效 rank 但非正方差、
  当前/lag2 zero-volume flags、负 volume/nonfinite/schema fail-closed，以及乱序和合法 calendar superset。
- 故障注入只把 trailing 无 bar grid row 的 `_u_ss` 改为 finite 异常：legacy 因实际 bar-key 投影保持不变，trace
  因 trace-only intermediate inconsistency 拒绝且不返回三表。

## 验证环境与结果

验证均在 source worktree 内、单进程、Windows fixture-only 完成：

- interpreter: `D:\Miniforge3\python.exe`
- `POLARS_MAX_THREADS=2`
- `OMP_NUM_THREADS=1`
- `PYTHONDONTWRITEBYTECODE=1`
- pytest 为确保 editable 安装不解析到主 checkout，额外将当前 worktree 的 `src` 放入本进程 `PYTHONPATH`；命令参数保持任务书原样。
- 未访问项目真实 `data/`、raw、ledger、run 产物、网络或外部账户。

正式通过阶段严格为：

1. `D:\Miniforge3\python.exe -m pytest -q tests/unit/test_classic_eleventh_batch.py -p no:cacheprovider --basetemp=artifacts/agent_runs/m2-r21-single-pass-trace/pytest-attempt-20260908-03`
   - exit `0`
   - native result: `23 passed, 358 warnings in 3.08s`
2. `D:\Miniforge3\python.exe -m ruff check --no-cache src/quant/factors/classic_eleventh_batch.py tests/unit/test_classic_eleventh_batch.py`
   - exit `0`
   - native stdout: `All checks passed!`
3. `D:\Miniforge3\python.exe -m mypy --cache-dir artifacts/agent_runs/m2-r21-single-pass-trace/mypy src/quant/factors/classic_eleventh_batch.py`
   - exit `0`
   - native stdout: `Success: no issues found in 1 source file`

此前尝试也保留在 source 内 fresh evidence 目录：

- `pytest-attempt-20260908-01`：收集阶段 exit `1`；解释器解析了主 checkout 的已安装 editable 包，未加载当前 worktree 新导出。
- `pytest-attempt-20260908-02`：`22 passed, 1 failed`；失败为测试 tie fixture 在不同 open 下的浮点 oracle，修正为共同 `open=128` 后使用 attempt-03 重新验证。

## 未运行项与边界

未运行 full suite、Linux/WSL Gate、runner/receipt/label/evaluate/publish、真实数据或网络、trial、经济收益验证、PAPER、LIVE，
也未运行 ETF 链。上述 Windows 结果只证明本交付的 fixture-level development validation，不证明 Linux 兼容性、数据覆盖、因子有效性、
promotion 或任何交易准入。

验证产生的 `artifacts/agent_runs/m2-r21-single-pass-trace` 仅为未提交证据/cache，未加入 exact3 staging。

## Source identity

- task: `M2-R21-SINGLE-PASS-TRACE`
- branch: `codex/m2-r21-single-pass-trace`
- exact base / pre-implementation HEAD: `b6998b7e9960eb089bf4e07034f9ed86c94fcbd0`
- implementation source commit: `6fd05834cca189df50b9fa2542df5da56f73e023`
- parent of implementation source commit: `b6998b7e9960eb089bf4e07034f9ed86c94fcbd0`
- the final documentation-only follow-up commit carries this completed delivery report; the implementation source identity above remains unchanged.

## 历史更正及 REWORK1 / STATIC_REWORK2 追加记录

本节严格追加在提交 `085e04488ba1d25bfdb1e3ef497efa148b9e8511` 的完整历史原文之后；上方前缀未删除、改写或补造。
历史前缀中记录的旧 `23 passed`、Ruff、mypy、import identity、旧失败历史及其退出码，因旧根目前只保留
mypy cache、没有可独立读取的 native stdout/stderr/exit 与三个 pytest attempt，均明确为不可独立核验。
本报告不重建旧日志、旧退出码或旧验证 SHA；历史 source commit 仅为代码历史身份，不是旧验证证据。

### REWORK1 可核验新证据

REWORK1 只在 exact2 中增加了测试与报告内容，production 未修改。其新证据根为：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework1\`。
在 source cwd、Windows fixture-only、`D:\Miniforge3\python.exe`、`POLARS_MAX_THREADS=2`、
`OMP_NUM_THREADS=1`、`PYTHONDONTWRITEBYTECODE=1`、当前 source `PYTHONPATH` 下，三个阶段的可读取 native
证据分别为：pytest `28 passed, 468 warnings in 4.49s`/exit 0；Ruff `All checks passed!`/exit 0；
production mypy `Success: no issues found in 1 source file`/exit 0；三份 stderr 均为空。
这些是 REWORK1 新运行的可核验证据，不是旧报告结果的恢复。REWORK1 的 module identity 仍是在普通 pytest
内部断言中验证，未构成产品阶段前冷导入闸门，故不替代本轮 §10.2 冷导入要求。
REWORK1 preflight 记录 production `26009 bytes / 3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`
与 test `43725 bytes / 99ee73c0d7e7b460c98c6a007082c8835fc4da5d2f4040e71f016261ca7ac82f`；REWORK2 当前 test identity
见下文。

### STATIC_REWORK2 变更与根因映射

本轮唯一 source exact2 变更为：

1. `tests/unit/test_classic_eleventh_batch.py`：删除 `sys` import 与普通
   `test_runtime_import_identity_is_current_worktree` 中无条件的 `D:\Miniforge3\python.exe` 断言，保留
   平台中性的 `module.__file__` 当前 source 定位断言；其他数学测试未改。
2. `docs/research/deliveries/M2_R21_SinglePassTrace交付报告.md`：恢复上述历史前缀并追加本节。

根因—现象—规则—最小修订—通过条件：

- 普通 unit 的根因是把验证机器的 Windows 解释器准入写进可移植业务测试，现象是合法 Linux/WSL
  解释器加载正确 source 也会失败；规则是普通 unit 不硬编码机器路径；最小修订是删除该断言而保留
  module source 定位；通过条件是普通 unit 不再依赖 Windows 盘符，本轮测试改动已满足。
- 产品前导闸门的根因是把 import identity 放在 pytest 内追认，现象是此前没有独立 cold-import 输出，
  不能阻止后续产品阶段；规则是冷导入必须是产品前置闸门；最小修订是按 §10.2 单独启动限定冷导入子进程，
  失败则后续阶段 UNRUN；本轮冷导入未通过，故该通过条件未满足。
- 历史更正的根因是 REWORK1 替换了旧报告段落，现象是历史前缀不可逐字比较；规则是历史只能保留并在末尾追加；
  最小修订是从 085e commit 恢复完整前缀后追加本节；通过条件由下方只读 diff 核验。

### REWORK2 preflight identity

本轮新 no-clobber 根唯一为：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2\`；
REWORK1 与原根保留且未清理/覆盖。preflight 文件为
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2\rework2_preflight.md`。

验证前记录：cwd 为 source worktree，branch 为 `codex/m2-r21-single-pass-trace`，dispatch HEAD 为
`557815c888b3886b76d810bb514b671e46add581`；解释器为 `D:\Miniforge3\python.exe`，file/product version
`3.13.13 / 3.13.13`，interpreter SHA256
`478CA44A015899FD0FF5AEACA9D407496F5C18EC454A6EC1FD36CF6D18C9A49F`。production identity 为
`26009 bytes / 3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`，与 §10.2 完全相符。
REWORK2 当前 test identity 为 `43625 bytes / 7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3abb4a06a677d376`；
REWORK1 test identity `43725 bytes / 99ee73c0d7e7b460c98c6a007082c8835fc4da5d2f4040e71f016261ca7ac82f`
仅用于证明本轮删除范围。manager-owned taskbook/review 的 dirty 状态原样保留，未修改。

只记录以下环境变量：`POLARS_MAX_THREADS=2`、`OMP_NUM_THREADS=1`、
`PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\src`。
没有输出完整环境、凭据、真实数据或经济路径。

### STATIC_REWORK2 验证结果（当前结论 STOP）

按要求首先尝试的 stage 1 child argv 为：

```
D:\Miniforge3\python.exe -c "import hashlib,pathlib,sys;from quant.factors import classic_eleventh_batch as m;p=pathlib.Path(m.__file__).resolve();expected=pathlib.Path(r'F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\src\quant\factors\classic_eleventh_batch.py').resolve();digest=hashlib.sha256(p.read_bytes()).hexdigest();print('sys.executable='+sys.executable);print('module.__file__='+str(p));print('production_bytes='+str(p.stat().st_size));print('production_sha256='+digest);assert p==expected;assert p.stat().st_size==26009;assert digest=='3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d'"
```

stage 1 native evidence：

- stdout：empty，文件
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2\cold-import-20260908-01.stdout.txt`
- stderr：`File "<string>", line 1 / import / SyntaxError: Expected one or more names after 'import'`，文件
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2\cold-import-20260908-01.stderr.txt`
- native exit：`1`，文件
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2\cold-import-20260908-01.exit.txt`

该失败来自 evidence wrapper 未将 `-c` 脚本作为单一 argv 传给 Python；native stderr 显示 Python 实际只把
`import` 作为脚本文本解析。因此 module 没有被 cold-import，stage 1 没有产生实际
`sys.executable`/module.__file__ 的运行输出，不能声称身份闸门已通过。该失败证据保留，不在本授权内盲重跑。

因为 stage 1 exit=1，按 §10.2 stage 2 与 stage 3 均为 `UNRUN`，没有伪造 stdout/stderr/exit：

- stage 2 预定命令：`D:\Miniforge3\python.exe -m pytest -q tests/unit/test_classic_eleventh_batch.py::test_runtime_import_identity_is_current_worktree -p no:cacheprovider --basetemp=artifacts/agent_runs/m2-r21-single-pass-trace-rework2/pytest`；UNRUN 标记文件：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2\pytest-identity-20260908-01.UNRUN.md`
- stage 3 预定命令：`D:\Miniforge3\python.exe -m ruff check --no-cache tests/unit/test_classic_eleventh_batch.py`；UNRUN 标记文件：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2\ruff-20260908-01.UNRUN.md`

本轮最终状态为 `STOP`，不是 `DELIVERY_READY`：冷导入前置闸门失败，REWORK2 通过条件未满足。没有 production
修改，没有 CONTRACT_DRIFT；没有 stage/commit。原 reviewer 后续需基于本追加 STOP 复验/裁定。

### 未运行项与 Windows/economic boundary

本轮未运行 REWORK2 pytest identity stage、REWORK2 Ruff、任何数学测试、production mypy、旧三阶段验证、full suite、
xdist、cold 之外的任何 Python、Linux/WSL Gate、runner、receipt、labels/evaluate/publish、真实 data/raw/ledger/financial
I/O、network、ETF、trial、PAPER、LIVE 或经济有效性验证。REWORK1 新证据仅证明其获批 Windows fixture-level 定向阶段；
旧证据不可核验；REWORK2 当前只有失败的冷导入尝试。任何结果都不证明 Linux 兼容性、真实数据覆盖、因子有效性、
promotion、经济有效性或交易准入。

## R21 EXECUTION_CORRECTION_GRANTED（REWORK2 execution correction 1）

### 载体更正与历史保留

本节是本轮唯一追加，未替换前文。前文 REWORK2 的 `Start-Process` 载体导致 `SyntaxError`、exit=1、后续
阶段 `UNRUN` 的 STOP 记录及其证据路径全部保留，作为本轮更正的历史证据；本节不删除、不改写、不冒充该旧结果。
本轮使用 PowerShell 原生 call operator `&` 与显式 argv array，argv 明确为 executable、`-c`、完整 script 三个
元素；未使用 `Start-Process`，未把参数数组扁平拼接成字符串，未新建通用 carrier。

本轮 project write 仅追加本 delivery；production、test、taskbook、roadmap、review、公共 rank、runner、config
及其他路径均未修改，未 stage/commit。manager-owned taskbook/review 的既有 dirty 状态保持原样。

### Preflight/source identity

唯一新 no-clobber evidence root 为：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2-execution-correction1\`。
REWORK2 原 root、REWORK1 root 与原 root 均保留，未清理或覆盖。preflight 文件为：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2-execution-correction1\execution_correction1_preflight.md`。

- cwd：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace`
- branch：`codex/m2-r21-single-pass-trace`
- manager HEAD：`557815c888b3886b76d810bb514b671e46add581`
- interpreter：`D:\Miniforge3\python.exe`，file/product version `3.13.13 / 3.13.13`
- interpreter SHA256：`478CA44A015899FD0FF5AEACA9D407496F5C18EC454A6EC1FD36CF6D18C9A49F`
- production：`26009 bytes / 3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`
- test：`43625 bytes / 7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3abb4a06a677d376`
- whitelist：`POLARS_MAX_THREADS=2`、`OMP_NUM_THREADS=1`、`PYTHONDONTWRITEBYTECODE=1`、
  `PYTHONPATH=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\src`

### 三阶段实际证据

严格按冷导入 → identity pytest → test-only Ruff 顺序执行，三阶段均 exit=0：

1. Stage 1 cold import 的实际 argv array 与完整 script 分别保存于：
   - `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2-execution-correction1\cold-import-20260908-01.argv.json`
   - `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2-execution-correction1\cold-import-20260908-01.script.txt`
   实际 native stdout：
   `sys.executable=D:\Miniforge3\python.exe`、
   `module.__file__=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\src\quant\factors\classic_eleventh_batch.py`、
   `production_bytes=26009`、
   `production_sha256=3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`。
   stdout、stderr、native exit 分别保存于同一 root 的
   `cold-import-20260908-01.stdout.txt`、`cold-import-20260908-01.stderr.txt`、
   `cold-import-20260908-01.exit.txt`；stderr empty，exit `0`。该子进程只冷导入目标模块并读取该生产文件
   完成身份核验，未调用 factor 计算，未读真实 data。
2. Stage 2 实际 argv 保存于
   `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2-execution-correction1\pytest-identity-20260908-01.argv.json`，实际命令为：
   `D:\Miniforge3\python.exe -m pytest -q tests/unit/test_classic_eleventh_batch.py::test_runtime_import_identity_is_current_worktree -p no:cacheprovider --basetemp=artifacts/agent_runs/m2-r21-single-pass-trace-rework2-execution-correction1/pytest-identity`。
   stdout 为 `. [100%]`、`1 passed in 2.23s`，stderr empty，native exit `0`；三者分别保存为同一 root 的
   `pytest-identity-20260908-01.stdout.txt`、`pytest-identity-20260908-01.stderr.txt`、
   `pytest-identity-20260908-01.exit.txt`。
3. Stage 3 实际 argv 保存于
   `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2-execution-correction1\ruff-20260908-01.argv.json`，实际命令为：
   `D:\Miniforge3\python.exe -m ruff check --no-cache tests/unit/test_classic_eleventh_batch.py`。
   stdout 为 `All checks passed!`，stderr empty，native exit `0`；三者分别保存为同一 root 的
   `ruff-20260908-01.stdout.txt`、`ruff-20260908-01.stderr.txt`、`ruff-20260908-01.exit.txt`。

### Correction 结论与边界

本轮 `EXECUTION_CORRECTION_PASS / VALIDATION_DONE_PENDING_REVIEW`：载体拆参根因已由显式 `&` argv 修正，
冷导入前置身份闸门、identity node 与 test-only Ruff 均有独立可读 native 证据。REWORK2 旧 SyntaxError STOP
仍是历史记录，不被本轮成功结果抹除。REWORK1 新证据、旧证据不可核验边界与本轮新证据保持分层；本轮不声称
重跑数学测试或全量测试，也不声称 test 文件整体 SHA 与 REWORK1 相同。

未运行数学测试、production mypy、旧三阶段、full suite、xdist、其他 Python/check、Linux/WSL Gate、runner、
receipt、labels/evaluate/publish、真实 data/raw/ledger/financial I/O、network、ETF、trial、PAPER、LIVE 或经济
有效性验证。以上仅为 Windows development fixture/import validation，不证明 Linux Gate、真实数据覆盖、因子有效性、
promotion、经济有效性或交易准入。原 reviewer 后续统一复验；在其复验前不合流、不提交、不退休 source。

## R21 DELIVERY_ONLY_ERRATUM_GRANTED：test SHA 逐处勘误

本节为 delivery-only erratum，仅追加于文件末尾；不改变 REWORK2 或 execution correction 的历史结论、测试/生产
bytes、任何 evidence/preflight 文件或 review。前文旧文字按原样保留，不回写、不覆盖、不补写旧证据。

### 错误位置与更正

以下旧抄录均为同一错误：把实际 64-hex test SHA 抄成了 62 字符版本。旧错误文字保留，仅在本节声明更正：

1. 本 delivery 的 REWORK2 preflight identity 段（原第 147 行）旧抄录：
   `7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3abb4a06a677d376`。
2. 本 delivery 的 correction preflight identity 段（原第 219 行）旧抄录：
   `7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3abb4a06a677d376`。
3. execution-correction preflight
   `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace\artifacts\agent_runs\m2-r21-single-pass-trace-rework2-execution-correction1\execution_correction1_preflight.md`
   的 test SHA256 旧抄录同为：
   `7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3abb4a06a677d376`。

正确的实际 test SHA 必须逐字为：

`7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3ababb4a06a677d376`

本 erratum 不修改或补写 execution-correction preflight/evidence 内的旧错误；它们继续作为历史现场保留。

### 交叉身份与边界

- source HEAD：`557815c888b3886b76d810bb514b671e46add581`。
- production 历史边界：`26009 bytes / 3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`。
- 当前 test 历史边界：`43625 bytes / 7202adfc3b84a073122c6d4f9d125d178d7f7a0fc1216c3ababb4a06a677d376`。
- 原 review 最新摘要按授权消息原样记录：`P0=0/P1=0/P2=1`、`16165 bytes`、SHA 前缀 `a506a91d`、后缀 `1443`；
  本轮不修改 review。

本轮仅追加本勘误，不重跑 pytest、Ruff、mypy、cold 或任何其他命令，不 stage/commit；REWORK2、execution correction
的验证结论和 Windows/economic boundary 均不变。
