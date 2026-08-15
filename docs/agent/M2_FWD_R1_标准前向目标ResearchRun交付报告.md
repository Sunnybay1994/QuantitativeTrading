# M2-FWD-R1：标准前向目标 Research Run 交付报告

日期：2026-08-16（Asia/Shanghai）

状态：实现与正常开发检查完成；7 路径唯一安全提交已形成；待 integration 吸收；未真实发布

Owner：框架开发 session（主 Agent）

执行模式：外部 Agent 暂停；不另设独立初验

## 1. 目标

将旧的 caller-frame、自定义目录式 forward observation 收束为 source-bound 标准
`LightweightResearchRunV1`：fresh 验证 canonical R10、由只读 repository 自签 source receipt、生成标准
target/schedule/source binding，并唯一复用现有 lightweight publisher。结论固定为 `RESEARCH_ONLY`。

冻结合同见：
[M2_FWD_R1_标准前向目标ResearchRun任务单.md](M2_FWD_R1_标准前向目标ResearchRun任务单.md)。

## 2. 基线与工作树

- branch：`codex/m2-forward-r1`
- exact base / 当前 HEAD：`121b672e99a905c38d993b7f6d07687e3371597c`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-forward-r1`
- source R10：`e43da184f942286ae7e8b79aa25bc540f692cb467821003ce193c9d35fb7a96f`
- source config SHA-256：
  `fd2ce82c4c3772752f383c7eb4439f1b89ee46d0272be4ce369eca84fbfaa9bf`

M2-SOURCE-R10 是唯一业务前置，且已通过 canonical retain 与 public fresh verify 关闭。
PIT first-run 只是 CPU 8–11 的调度优先项；FWD-R1 不依赖 financial snapshot 或 PIT READY。

## 3. 当前静态改动

1. 新增 `quant.data.m2_forward_source_repository`：bounded/stable read、路径与实体防护、两张 canonical
   frame、原始文件清单、逻辑摘要及 canonical source receipt。
2. 重构 `run_s2_forward_observation`：删除裸 frame/config mapping 输入和自定义 publisher；增加 source
   public fresh 双验、source config/report/manifest 绑定、repository 二次 stable load、标准 run 构造与唯一
   lightweight publisher。
3. forward config 精确改绑 canonical R10 run 与其 source config 物理 SHA。
4. 新增 repository 定向测试并改写 runner 定向测试，全部使用临时数据和临时 source bundle，不依赖机器
   canonical artifact。
5. 生产代码不 import execution/reporting，不包含 PAPER/账户/订单入口，不修改任何 `__init__.py` 或
   `lightweight_run.py`。

## 4. 已完成的非 Python 检查

- branch/worktree/HEAD 与授权精确一致；开始时 clean。
- 当前改动路径精确限制在任务书 7 路径白名单内。
- `git diff --check`：无 whitespace error；仅 Windows checkout 的正常 LF→CRLF 提示。
- 静态搜索未发现旧 `publish_forward_observation`、旧 custom schema 或 custom publisher 的代码引用残留。
- forward config 中旧 `05eee...` / `51755c...` 绑定已消失，现为 canonical R10 identity。

## 5. 已完成开发检查

FWD-R1 始终固定在授权基线 `121b672e99a905c38d993b7f6d07687e3371597c`，未 rebase/merge。PIT
first-run prerequisite 退休后，统筹将 CPU 8–11 明确释放给 FWD-R1。以下检查全部使用唯一实例、
`BelowNormal`、affinity `0xF00`、数值线程 `<=2`，严格串行：

1. `D:\Miniforge3\python.exe -m pytest tests/unit/test_m2_forward_source_repository.py tests/unit/test_m2_forward_observation.py -q -p no:cacheprovider --basetemp <system-temp>`：
   `17 passed, 1 skipped, 312 warnings in 13.70s`。唯一 skip 是宿主无法创建某一 alias mutation 的平台能力分支；
   系统 basetemp 已精确清理。
2. `D:\Miniforge3\python.exe -m ruff check` 定向两生产模块和两测试文件：
   `All checks passed!`。
3. `D:\Miniforge3\python.exe -m mypy` 定向两生产模块：
   `Success: no issues found in 2 source files`；外部 mypy cache 已精确清理。
4. cold import：`FWD_COLD_IMPORT_OK`，两模块 `__file__` 均精确位于本 FWD worktree `src`，
   `load_m2_forward_source_slice` 与 `publish_forward_research_run` 均为 callable。
5. 收尾巡检：`NO_0xF00_PROCESS`、`NO_FWD_TASK_TEMP`；worktree `artifacts/`/`data/` 下
   无 ignored 正式产物。

## 6. 未执行与剩余边界

- 未运行真实 2026-08-31 forward publish；当前日期和数据均不构成真实 forward 观察完成证据。
- 真实 2026-08-31 publish 需要单独运行授权；本次开发检查通过也不会自动触发它。
- 未生成 `PAPER_CANDIDATE`，未触发 S2 admission、M4 loader、PAPER、OMS 或订单。
- 未执行 Linux/WSL 验证；本项目当前阶段按用户指示暂不考虑 Linux 实现。
- 未 rebase、merge、push、联网或修改根 canonical artifact；只对 7 个白名单路径形成唯一安全提交。

## 7. 提交、合流与退出条件

开发检查、临时目录、资源残留和 7 路径安全提交闭包已完成。尚待顺序完成：

1. 统筹将该提交吸收进 integration，完成 ancestor 确认与必要的合并后最小回归；
2. Owner（框架开发 session，主 Agent）明确释放，工作树 clean、无活跃进程、无临时目录、
   无 ignored 正式产物；分支的保留或归档由统筹裁定。

## 8. 最终交付状态

当前为 **实现、正常开发检查与安全提交完成，待 integration 吸收**，不是真实
2026-08-31 FWD 发布、PAPER 准入或更高 Gate 通过。
