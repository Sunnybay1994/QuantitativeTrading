# M3 G6A R2：共享 Publication 首写前 Root 复验独立复验报告

日期：2026-08-09  
角色：未参与 R2 返工的全新独立复验 Agent  
结论：**PASS；可进入主 Agent 最终验收，但不等于正式全 work、ext4/Linux Gate 或 M3 Gate 通过**

## 1. 范围与边界

本轮完整读取并逐项核对了 G6A 任务单第 13 节、R1 独立初验 FAIL、R2 返工交付报告、共享
`_artifact_publication.py`、G5A/G5B/G6A 三个公共 builder 及其直接 publication tests。生产代码和实现者测试
始终只读；唯一新增文件是本报告。未联网、未扫描 `data/legacy`、未读取或写入正式 G1 artifact/journal，
未 add/commit。

Windows 原生与 WSL Miniforge base 的工程证据均已取得；WSL 项目仍位于 `/mnt/f` DrvFS，故该证据不代表
ext4/Linux Gate。正式全 folds/horizons evaluation、真实数据性能、acceptance threshold 和 M3 Gate 均未运行或关闭。

## 2. R1 阻断闭环

R2 在 `ArtifactPublication.write_stream()` 中增加了两个 current-root 复验点：每个 `_open_output()` 前一次，
exclusive open、记录 owned identity 后、调用 caller writer 前再一次。原 POSIX 锚定 dir-fd、Windows
no-share-delete directory handle、exclusive-create、fsync、commit、identity-aware rollback 与 no-clobber 语义均未退化。

独立源码调用图确认：

1. builder 进入 publication，acquire caller-created 空 root 并取得实体 anchor；
2. fresh verifier/训练/预测/评价数学可以在 lease 存续期间执行，但每个最终输出在 open 前重新比对 caller path；
3. open 成功后，writer 前再次比对；若此窗口发生漂移，descriptor 被关闭，owned 空 inode 进入精确 rollback，writer 为 0；
4. writer 后仍执行 flush/fsync、owned identity/readback、exact entries 与 commit 前后 current-root 复验。

因此 R1 的“POSIX fresh/数学窗口已漂移但三个 writer 仍执行”路径已被首个输出前关闭。

## 3. 独立对抗证据

### 3.1 实现者未使用的 check/open 间竞态

独立无落盘探针不是在 fresh callback 中提前替换，而是包装共享 `_open_output()`：让第一次 output 的
pre-open `_require_current_root()` 已成功后、真正 anchored open 之前才 rename 原 root 并在 caller path 创建新空目录。
这直接覆盖“检查与 open 之间”的更窄竞态。探针分别通过 G5A `build_model_artifact`、G5B
`build_prediction_artifact`、G6A `build_evaluation_artifact` 三个公共入口运行。

WSL base `/mnt/f` 结果：

```text
G5A (attempted=True, replaced=True, writer_calls=0)
G5B (attempted=True, replaced=True, writer_calls=0)
G6A (attempted=True, replaced=True, writer_calls=0)
INDEPENDENT_BETWEEN_CHECK_AND_OPEN_PASS
```

三者都只暴露各自稳定 `*_ARTIFACT_INVALID`，`cause/context is None`，新 caller path 与旧锚实体最终均无
retained bytes。该证据说明第二次复验确实封闭 pre-check 与 open 之间的 TOCTOU，而不是只对实现者固定替换点绿色。

### 3.2 open 后、writer 前与平台分支

共享原语定向测试真实执行并通过：

- `test_r2_publication_rechecks_root_after_open_before_writer`：POSIX 分支在 descriptor/owned identity 已取得后替换
  root，writer 为 0，owned 空文件精确回滚；本轮另以 `-vv` 单项重跑，确认没有 skip；
- Windows 上目录 handle/no-share-delete 阻止 rename，攻击 callback 在 writer 前被拒绝；公共 builder 独立探针对
  G5A/G5B/G6A 的结果分别为 `(root_checks, writer_calls, replaced) = (9,3,False)`、`(7,2,False)`、
  `(9,3,False)`，即攻击未改变 root，正常 artifact 仍可发布；没有把 Windows 行为误报为 POSIX 替换成功。

### 3.3 fresh/数学窗口、rollback 与竞争文件

- G6A direct test 分别在 fresh label verifier 返回窗口和 `_parquet_bytes` 数学/序列化窗口替换 root；两条 POSIX
  分支均 writer=0、双目录零 retained，Windows 分支均由打开的目录 handle 阻止 rename；
- G5A fresh alignment、G5B predict/math、G6A fresh/math 至少各有一个公共 builder root-replacement 回归，并由
  本轮三公共入口的更窄 check/open 探针补强；
- 三套 writer ValueError/RuntimeError、fsync、rollback-unlink failure、owned inode 被竞争文件替换、并发抢占同名
  文件测试均通过。rollback 只删除 `samestat` 仍等于记录 identity 的 owned 文件；竞争文件保留，rollback 无法证明
  完整时使用独立 `*_ROLLBACK_FAILED`，不会误报普通 artifact invalid；
- 公共边界对 hostile writer、reader、fresh verifier 的私有路径/sentinel 只返回稳定码，测试逐项断言
  `__cause__ is None`、`__context__ is None`。

### 3.4 G6A fresh verifier 与数学闭包回归

R1 已通过且 R2 未改变的 G6A 主体在本轮全组回归继续绿色：builder/verifier 各自 fresh G1→G5B prediction 与
独立 label、五层集合和四个总 count 分母、八状态优先级、Pearson/Spearman tie、sample-std ICIR、17-input/
3-output exact receipt、wholesale 重签拒绝、label 缺失不降低 prediction coverage。R2 diff 只改变共享 publication
复验点及直接测试，没有改动上述数学、manifest 或 receipt 接口。

## 4. 验证命令与结果

### Windows 原生 Miniforge

```powershell
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest `
  tests/unit/test_m3_formal_model_artifact.py `
  tests/unit/test_m3_formal_prediction_artifact.py `
  tests/unit/test_m3_formal_evaluation_artifact.py -q `
  --basetemp=.pytest-g6a-r2-independent-win-20260809
```

结果：`38 passed, 44035 warnings in 465.08s`。

```powershell
D:\Miniforge3\python.exe -m ruff check `
  src/quant/research/m3/_artifact_publication.py `
  src/quant/research/m3/model.py src/quant/research/m3/predictions.py `
  src/quant/research/m3/evaluate.py `
  tests/unit/test_m3_formal_model_artifact.py `
  tests/unit/test_m3_formal_prediction_artifact.py `
  tests/unit/test_m3_formal_evaluation_artifact.py
D:\Miniforge3\python.exe -m mypy --no-incremental `
  src/quant/research/m3/_artifact_publication.py `
  src/quant/research/m3/model.py src/quant/research/m3/predictions.py `
  src/quant/research/m3/evaluate.py
```

结果：Ruff `All checks passed!`；mypy `Success: no issues found in 4 source files`。

### WSL Miniforge base，`/mnt/f` DrvFS

对应三文件 pytest 使用 `/tmp/pytest-g6a-r2-independent-wsl-20260809` basetemp：
`38 passed, 44035 warnings in 246.44s`。对应 Ruff PASS；mypy `4 source files` PASS。
open 后/writer 前单项 `-vv`：`1 passed`，无 skip。

warning 均为既有 Pandera/Polars deprecation 和工作树 `.pytest_cache` 无写权限；pytest 已使用唯一 basetemp，
不影响结论。独立探针最初一次因临时 fixture 父目录未创建而在进入产品逻辑前失败；修正探针装配后重跑通过。
另一次经 `conda run ... python -` 传 stdin 没有产生探针输出，随后直接使用同一 WSL base 环境解释器重跑并取得
上面的明确断言证据；两者都不是产品测试失败。

## 5. Git 与最终判定

`git status` 显示该历史工作树已有大量 G4B–G6A 未跟踪/脏文件；本轮全部保留。R2 白名单文件在此工作树仍是
未跟踪状态，因而没有可信的 Git pre/post diff 基线；`git diff --check` 对可见 tracked diff 未报空白错误，未声称
不存在的 Git 差异。

R1 唯一阻断已由共享 publication 的 pre-open 与 post-open/pre-writer 两次 current-root 复验关闭；Windows
no-share-delete 与 POSIX 可替换分支均有真实证据，G5A/G5B/G6A 公共入口、writer=0、双目录零 retained、精确
rollback/no-clobber 及异常脱敏均符合任务单第 13 节。故本轮独立复验结论为 **PASS**，可以进入主 Agent 最终验收。

仍未关闭：正式全 folds/horizons G6A、正式 G6B、ext4/Linux Gate、真实数据性能、acceptance threshold 与 M3 Gate。
