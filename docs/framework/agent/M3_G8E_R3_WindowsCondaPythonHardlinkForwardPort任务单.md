# M3 G8E R3 Windows Conda Python Hardlink Forward-Port 任务单

状态：实现与普通开发检查完成；待项目结构统筹合流；actual worker、retained 与 successor 未授权。

## 1. 目标与来源

以 integration `de32d9143a732caa7c3f92a21403e80a80bd0866` 为唯一基线，把历史提交
`71dffa5c6860738dcfceb86f94d9918e71daeb2b` 已完成任务、独立复验和主验的
Windows Conda 当前解释器 hardlink 语义，与现有 PROJECT-only REPRO root-topology 修复组合。

当前阻断是 `reproducibility._run_stage` 仍把 `Path(sys.executable)` 当普通 artifact，
通过要求 `st_nlink == 1` 的 `_real_file` / `_file_sha256` 验证。Windows Conda 当前
解释器可合法为多硬链接文件，因此未来 Windows successor 会在 resolver 和 StageRunner 之前失败。

## 2. 冻结实现

- 新增 `_current_python_executable`：只接受 absolute、exact current
  `sys.executable` canonical path 且 `samefile` 的普通非空文件；supplied leaf 与 resolved leaf
  均拒绝 symlink/reparse。Windows 允许 `st_nlink >= 1`，非 Windows 仍要求 `st_nlink == 1`。
- 新增 `_python_executable_sha256`，只哈希上述 helper 验证后的解释器。
- `_run_stage` 入口、comparison key 和 stage result 使用同一专用 SHA。
- worker audit 中的 `Path(sys.executable)` 使用同一专用 SHA。
- 保持 `_project_only_artifact_roots(root)`、PROJECT-only receipt aliases、comparison identity
  公式、receipt schema、worker protocol和公共错误码不变。
- 普通 artifact 的 `_real_file`、`_file_sha256`、`_digest_for_path`、`_regular_files` 不变。

历史独立复验已记录父目录 junction 边界；本包只 forward-port `71dffa5` 已验收语义，
不扩展为完整路径链 reparse 治理。

## 3. 唯一写白名单

1. `src/quant/research/m3/reproducibility.py`
2. `tests/unit/test_m3_reproducibility.py`
3. 本任务单
4. `docs/framework/agent/M3_G8E_R3_WindowsCondaPythonHardlinkForwardPort交付报告.md`

禁止修改 acceptance、orchestration、run_state、配置、导出、roadmap、共享 SSOT 或其他路径。

## 4. 必须覆盖

1. Windows exact current Conda `sys.executable` 在 `st_nlink >= 2` 时实际 PASS，不能 skip。
2. 当前解释器的额外 hardlink path 即使 `samefile` 仍拒绝并精确清理。
3. 非当前解释器在 resolver 前稳定拒绝，公共错误 cause/context 为空。
4. leaf symlink/reparse fail closed；宿主不允许创建 symlink 时该独立反例可 skip。
5. 普通 artifact hardlink 继续被 `_real_file`、`_file_sha256`、`_digest_for_path` 和
   `_regular_files` 拒绝。
6. 既有真实嵌套 root 反例、PROJECT-only receipt、首次发布和 resume 不再调用 worker断言不得削弱。

## 5. 开发检查

Windows Miniforge、BelowNormal、CPU affinity `0xF00`、数值线程不超过2、单实例串行执行：

1. `pytest tests/unit/test_m3_reproducibility.py -q -p no:cacheprovider`；
2. Ruff：生产文件和单元测试；
3. mypy：生产文件；
4. reproducibility cold import；
5. `git diff --check`、四路径 scope、临时/cache/进程残留检查。

不得运行上次 acceptance 集合、actual worker、retained resume、successor、readiness 或全量回归。

## 6. 停止与退出条件

若需扩大白名单、放宽普通 artifact hardlink、改变 comparison identity/receipt schema、削弱
PROJECT-only测试、处理父目录 junction、或启动真实链，立即停止重新裁定。

退出时只可声明 hardlink 语义已与 PROJECT-only 修复组合并完成普通开发检查；四路径形成单一安全提交，
由项目结构统筹合流。本任务不自行合流或删除 worktree。
