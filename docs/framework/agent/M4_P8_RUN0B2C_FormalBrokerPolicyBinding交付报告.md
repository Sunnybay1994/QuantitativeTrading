# M4 P8 RUN-0B2C：Formal Broker Policy Binding 交付报告

日期：2026-08-09
状态：实现与自验完成；待独立初验与主 Agent 终验

## 1. 交付结果

按冻结任务书新增纯内存、进程内的 formal PAPER broker policy binding：

- 只接受 exact `VerifiedPaperRuntimeEnvironment` 与 `VerifiedPaperExecutionPolicy`，并按 runtime → policy 顺序
  调用两个既有 public fresh verifier；RUN-0A existing preflight 成功返回 `None` 后继续使用原 exact
  environment，policy fresh 返回值必须 exact 等于传入 capability；
- classification 固定为 `formal-paper-simulation`，session、runtime/config identity、policy/cost identity、五类
  adapter/fill/fault/finality/clock version 以及 FX `None` 全部只从 fresh capability 读取；
- binding identity 使用平台无关 canonical JSON 绑定全部公开字段和显式 UTC `verified_at`；唯一私有 closure mint
  使用 process-local HMAC attestation 绑定同一完整 payload；
- existing verifier 先验证 exact type 与私有 attestation，再 fresh 验证两个上游 capability，以原签发时点重建
  binding 并 exact compare；跨 environment/config/policy/session/version、clone、subclass 和 reload old token 均拒绝；
- capability 不可 pickle；模块 `__all__` 只有错误、类型、bind、verify 四项，无 generic signer/key/builder；
- 四类公开失败码稳定脱敏，hostile verifier 的递归异常图、路径、SQL、TOKEN 与 marker 不进入 cause、context
  或 repr。

## 2. 文件范围

- 新增 `src/quant/execution/paper_broker_binding.py`
- 新增 `tests/unit/test_paper_broker_binding.py`
- 更新本任务单状态
- 新增本交付报告

未修改 runtime、policy、B1 broker descriptor/store、gateway、service、CLI、migration、soak、package root 或配置；
未创建/open root、SQLite、journal、socket、日志或缓存，未读取墙钟，未发起网络请求。

## 3. 对抗覆盖

新增测试覆盖：

- fresh bind、跨平台稳定 canonical identity、晚时点 existing fresh exact；
- development runtime、B1 `PaperBrokerPolicyDescriptor`、dict/duck/object-new/subclass/clone/pickle/reload token；
- environment config identity、policy identity/session/nested version 交叉拼接与漂移；
- runtime verifier 失败零结果、policy verifier 返回非 exact capability、naive/non-UTC/early `now`；
- runtime/policy verifier hostile `ValueError`/`RuntimeError` 递归 cause/context 图脱敏；
- monkeypatch `open`、socket、SQLite、logging、wall clock 证明绑定路径零副作用；
- from-star exact 四项、无 generic mint/key、caller 无 classification/version/identity 参数；
- cold import 不加载 broker store/SQLite、soak、Qlib、LightGBM 或 MLflow。

同时运行 B2B policy 与 RUN-0A runtime 直接上游合同，覆盖 policy whole-rehash、same-bytes inode replacement、
retained nested drift 与 runtime capability freshness。第一次 Windows 联合命令把 `basetemp` 置于项目树内，按
runtime 冻结合同得到 4 个 `PAPER_RUNTIME_LAYOUT_INVALID`；改用系统临时目录后全部对应测试通过。

## 4. 验证证据

Windows 原生 Miniforge，隔离 worktree `PYTHONPATH=src`：

```text
D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_paper_broker_binding.py tests/unit/test_paper_policy.py -q
40 passed, 1 skipped in 7.40s

D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_runtime.py -q \
  --basetemp=%TEMP%\quant-run0b2c-impl-win
19 passed, 30 skipped in 4.77s

D:\Miniforge3\python.exe -m ruff check \
  src/quant/execution/paper_broker_binding.py tests/unit/test_paper_broker_binding.py
All checks passed!

D:\Miniforge3\python.exe -m mypy \
  src/quant/execution/paper_broker_binding.py tests/unit/test_paper_broker_binding.py
Success: no issues found in 2 source files
```

Windows 唯一 policy skip 是当前主机 symlink 权限；runtime skips 是冻结的 WSL formal/platform-only 用例。新
binding 测试含 cold import 并通过。

WSL Miniforge base，当前 worktree 位于 DrvFS：

```text
python -m pytest tests/unit/test_paper_broker_binding.py \
  tests/unit/test_paper_policy.py tests/unit/test_paper_runtime.py -q \
  --basetemp=/tmp/quant-run0b2c-impl-wsl
90 passed in 9.25s

python -m ruff check src/quant/execution/paper_broker_binding.py \
  tests/unit/test_paper_broker_binding.py
All checks passed!

python -m mypy src/quant/execution/paper_broker_binding.py \
  tests/unit/test_paper_broker_binding.py
Success: no issues found in 2 source files
```

## 5. 诚实边界

- 当前 WSL 路径是 DrvFS；以上只证明 development 工程合同与双平台兼容，不关闭 WSL2/ext4 formal Gate。
- 单元测试通过隔离 monkeypatch 模拟两个 public fresh verifier 的成功返回，并额外运行其真实直接上游合同；
  没有在 Windows/DrvFS 伪造正式 runtime capability 或 formal broker 发布物。
- 本包没有创建 formal account descriptor、store/gateway/service/factory、TargetLoader、LedgerContext、scheduler
  或 soak；后续仍须先冻结并实现 formal PAPER account SSOT/loader。
- worktree 含大量前序既有脏文件和测试目录；本轮只写任务白名单文件，未清理、暂存或提交其他改动。
