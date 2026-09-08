# M3 G0：`py312` 环境创建与兼容探针主 Agent 最终验收报告

日期：2026-07-15  
结论：**G0 Python 子项通过主验；正式 G0 Gate 尚未关闭**

## 1. 验收链

- 主任务：[`M3_G0_py312环境创建与兼容探针外部闭环任务单.md`](M3_G0_py312环境创建与兼容探针外部闭环任务单.md)
- 首次创建/网络阻塞：[`M3_G0_py312环境创建与兼容探针交付报告.md`](M3_G0_py312环境创建与兼容探针交付报告.md)
- 官方索引重试：[`M3_G0_py312环境网络阻塞重试任务单.md`](M3_G0_py312环境网络阻塞重试任务单.md)、
  [`M3_G0_py312环境网络重试交付报告.md`](M3_G0_py312环境网络重试交付报告.md)
- 离线 wheelhouse：[`M3_G0_py312离线Wheelhouse返工任务单.md`](M3_G0_py312离线Wheelhouse返工任务单.md)、
  [`M3_G0_py312离线Wheelhouse返工交付报告.md`](M3_G0_py312离线Wheelhouse返工交付报告.md)
- `gym` 单 sdist 例外：[`M3_G0_py312_Gym单依赖构建返工任务单.md`](M3_G0_py312_Gym单依赖构建返工任务单.md)、
  [`M3_G0_py312_Gym单依赖构建返工交付报告.md`](M3_G0_py312_Gym单依赖构建返工交付报告.md)
- `editables` 增量：[`M3_G0_py312_Editables增量返工任务单.md`](M3_G0_py312_Editables增量返工任务单.md)、
  [`M3_G0_py312_Editables增量返工交付报告.md`](M3_G0_py312_Editables增量返工交付报告.md)
- 独立复验命令修订：[`M3_G0_py312独立复验命令修订任务单.md`](M3_G0_py312独立复验命令修订任务单.md)
- 全新独立复验：[`M3_G0_py312环境创建与兼容探针独立复验报告.md`](M3_G0_py312环境创建与兼容探针独立复验报告.md)

## 2. 安装闭环与通用教训

`py312` 已创建于 `/home/mabw/miniforge3/envs/py312`，Python 为 3.12.13。WSL 中 base Python 能解析
PyPI、py312 Python 不能稳定解析，因此没有修改 DNS、hosts、代理或 pip 配置，而是由 base **只下载**目标
CPython 3.12 wheel，再由 py312 `--no-index` 离线安装。

官方 `pyqlib==0.9.7` 有 cp312 manylinux wheel。其依赖 `gym==0.26.2` 只发布 sdist，故仅对这个声明支持
Python ≥3.6 的纯 Python 依赖做离线 wheel 构建；Qlib 本体和其他 206 个依赖保持 wheel-only。Hatchling 的
editable hook 另需 `editables==0.6` wheel，纳入明确增量后安装完成。全过程未向 base 安装、升级或卸载包。

首个复验会话因 Windows→WSL 引号没有完成两个 hash 检查；这不是环境缺陷。修订任务改用已经实测的直接
`wsl.exe -e` 命令，并把原交付报告未冻结 envelope 的 `f306...` 聚合 hash 降为 P2，采用透明命令
`sha256sum *.whl | sha256sum` 作为可复现证据。

## 3. 主 Agent 证据

主 Agent 独立复核结果：

```text
py312 Python / pyqlib                     3.12.13 / 0.9.7
pip check                                 No broken requirements found
Qlib / Alpha158 / LGBModel                import PASS
readiness Python / Qlib issues            [] / []
py312 readiness                           41 passed, 1 deselected
base readiness                            42 passed
base raw SHA                              568106ba05556241e105fab9b7ce4712a5a5ff4680f87c3160f4f1ab0750d750
base canonical SHA                        77329bcb2c14db6cd2925053f4bde047969a3c100cab7b53f0fc192b8de57e78
wheelhouse                                mode 0700, 207 wheel, 0 other/symlink/multi-link
wheelhouse transparent aggregate SHA      90cccbb1f8abfe355e2861c9599899d18b2a343eaa0462d0d1daa745bb727b0d
```

py312 被排除的单测是专用于“base 环境应暴露 Python 或 Qlib 未就绪错误”的断言，不能在已就绪 py312 中成立；
报告明确披露为 `1 deselected`。公开示例配置仍是 `meta.enabled=false`，路线图在本报告通过后只勾选 G0 Python
子项。

## 4. 限制

- NumPy 在当前 WSL1 报 `longdouble` 探测 warning；Qlib 还提示未安装 CatBoost、XGBoost、PyTorch 可选模型，
  均不在本任务范围且未导致探针失败；
- `/tmp/quant-m3-g0-py312-wheelhouse` 暂时保留为离线复现证据，未移动进项目或提交；
- 本子项只证明 Python/Qlib 兼容环境可用。完整 G1 数据、Qlib provider、Alpha158 真实数据运行、模型训练、
  MLflow 与正式 G0/G2/G3/G5/G8 Gate 尚未验收；`meta.enabled` 继续保持 `false`；
- 项目主体、核心回归和交易运行时仍在 base，Qlib 不进入 base 或交易必需依赖。
