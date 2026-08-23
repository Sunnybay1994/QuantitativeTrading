# M3 G8E R3 Windows Conda Python Hardlink Forward-Port 交付报告

状态：实现与普通开发检查完成；待项目结构统筹合流。actual worker、retained、successor、readiness 与 M3 Gate 均未授权或验证。

## 1. 交付结论

历史 `71dffa5c6860738dcfceb86f94d9918e71daeb2b` 已完成任务、独立复验和主验的
Windows current Conda Python hardlink 门禁，已最小 forward-port 到 integration
`de32d9143a732caa7c3f92a21403e80a80bd0866`，并保留现有 PROJECT-only root-topology 修复：

- REPRO 仅对 absolute、exact current `sys.executable` canonical path 且 `samefile` 的解释器使用专用门禁；
- supplied/resolved leaf 继续拒绝 symlink/reparse，Windows允许 `st_nlink >= 1`，非Windows仍要求 `st_nlink == 1`；
- `_run_stage` 入口、comparison key和worker audit统一使用专用解释器SHA；
- `StageRunner`、external inputs、outputs和receipt继续只使用PROJECT root；
- 普通artifact的 `_real_file`、`_file_sha256`、`_digest_for_path` 和 `_regular_files` 未放宽。

comparison identity公式、receipt schema、worker protocol、公共错误码与其他模块均未修改。

## 2. 精确改动范围

1. `src/quant/research/m3/reproducibility.py`
   - 新增 `_current_python_executable` 与 `_python_executable_sha256`；
   - 三条解释器门禁/SHA路径统一改用专用helper。
2. `tests/unit/test_m3_reproducibility.py`
   - 保留真实嵌套root、PROJECT-only receipt、首次发布和resume断言；
   - 增加nlink≥2正向、额外hardlink path、symlink leaf、普通artifact hardlink、resolver前非当前解释器拒绝等反例。
3. `docs/framework/agent/M3_G8E_R3_WindowsCondaPythonHardlinkForwardPort任务单.md`
4. 本交付报告。

未修改 acceptance、orchestration、run_state、配置、导出、roadmap、共享SSOT或历史retained字节。

## 3. 普通开发检查

检查均在 Windows `m3chain312` 环境中串行执行，承载为BelowNormal、CPU affinity `0xF00`，数值线程不超过2：

- interpreter preflight：`D:\Miniforge3\envs\m3chain312\python.exe` 为105288字节HardLink，hardlink list精确含env与conda pkgs两项；
- focused unit：`10 passed, 2 skipped in 8.69s`；nlink≥2正向、普通artifact与非当前解释器节点实际PASS；两个skip分别为沙箱不允许在D盘创建额外hardlink、宿主无symlink权限；
- 额外hardlink单节点在非沙箱边界实际 `1 passed in 4.38s`，`finally` 后临时alias为0，原解释器hardlink list恢复为精确两项；
- Ruff测试文件全规则：`All checks passed!`；
- Ruff生产文件排除既有未改的 `I001/BLE001/UP022/TRY004` 基线后，其余规则：`All checks passed!`。首轮全规则如实暴露7个既有项，未通过扩大本任务去修改历史脱敏、subprocess或异常类型；
- mypy：`Success: no issues found in 1 source file`；
- cold import：`M3_G8E_R3_COLD_IMPORT_OK`，并断言模块来自本worktree、当前解释器nlink≥2且专用门禁通过；
- focused/targeted basetemp与解释器目录临时hardlink已精确清理。

所有测试中的worker均为既有deterministic fake；未运行actual worker、retained resume、successor、readiness、acceptance集合或全量回归。

## 4. 剩余边界

- 历史独立复验记录的父目录junction边界没有在本forward-port中扩展；处理它需要另行冻结路径链合同。
- 本提交只关闭未来Windows successor在REPRO入口被合法Conda hardlink拒绝的问题，不证明真实worker或后续stage可通过。
- 历史 `codex/m3-g8e-r2-windows-hardlink@71dffa5` 在本提交由统筹合流并archive前继续保留。
- 本任务不自行合流或删除worktree。
