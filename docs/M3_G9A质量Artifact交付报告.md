# M3 G9A 质量 Artifact 交付报告

日期：2026-08-13  
状态：主 Agent 串行实现与正常开发检查完成；未执行真实全量质量命令，未宣布 M3 Gate 通过

## 完成内容

- 新增固定命令质量边界 `quality_gate.py`：命令注册表固定为 pytest、Ruff、mypy 和 fresh-process import isolation，调用者不能传入 argv、shell、timeout 或忽略项。
- 质量 key 同时绑定当前代码、完整依赖指纹和版本化配置 digest；执行前后重新测量，任一漂移均拒绝发布。
- 命令日志先规范化 workspace/Python 路径，再扫描绝对路径、凭据形态与 NUL；只有四项退出码均为 0 才通过既有 StageRunner 发布五文件质量目录和 receipt。
- verifier 重新验证报告、五个输出、全部源码/config/pyproject input digest、receipt scope/key，以及当前代码/依赖/配置身份。
- 将 readiness 的 Qlib 可用性探测下沉至唯一 `qlib_adapter.py`，闭合冻结的重依赖 import allowlist，不改变 readiness 对外判断。
- `quant.research.m3` 继续采用 lazy export，冷导入不会引入质量模块或重依赖。

## 开发验证

- `tests/unit/test_m3_quality_gate.py`: `4 passed`。
- readiness + quality + orchestration 邻接：`81 passed`。
- 定向 Ruff：通过。
- `mypy`（quality gate、Qlib adapter、readiness）：通过。
- fresh subprocess import-isolation 命令：通过；`quant.domain`、`quant.strategies`、`quant.backtest` 导入后不加载 Qlib、LightGBM、MLflow。

## 边界与剩余风险

- 本轮使用窄 `CommandExecutor` 运行确定性开发测试，没有再次执行耗时的真实全量 pytest/Ruff/mypy；真实 executor 已固定为当前 Python、`shell=False`，应由最终质量准入运行实际命令。
- Windows 开发反馈不替代 WSL/Linux Gate；用户当前要求暂不考虑 Linux 实现。
- G9B–G9G、真实 tracking/全链证据和最终 acceptance 尚未完成，因此本报告不表示 G9 或 M3 Gate 通过。
