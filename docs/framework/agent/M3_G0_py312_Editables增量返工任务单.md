# M3 G0：`editables` wheel 增量返工任务单

日期：2026-07-15  
状态：主 Agent 已复核 Hatchling PEP 660 缺口；退回原 Terra Medium 实现会话

## 1. 冻结增量

官方 PyPI `https://pypi.org/pypi/editables/json` 当前稳定版为 `0.6`，`Requires-Python >=3.7`，同时发布
`editables-0.6-py3-none-any.whl` 和 sdist。本轮只允许下载、安装前者；不得下载 sdist。

现有 wheelhouse 必须仍是当前用户 0700、只有普通 `.whl`、无 symlink/hardlink alias，且排序清单总 SHA 为前轮
记录的 `55f9b398fd56b1ff5111b7c3f0fa0dafb7d222a37e7d1067d5de223d6993051c`；不一致即停止。

## 2. 下载与离线安装

取得 base 前指纹后，用 base pip 只下载、不安装：

```bash
python -m pip download --dest /tmp/quant-m3-g0-py312-wheelhouse \
  --index-url https://pypi.org/simple --retries 10 --timeout 30 --no-cache-dir \
  --only-binary=:all: --no-deps 'editables==0.6'
```

记录 wheel 的 size/SHA，确认无 sdist。随后 `py312` 只离线执行：

```bash
conda run -n py312 python -m pip install --no-index \
  --find-links /tmp/quant-m3-g0-py312-wheelhouse 'editables==0.6'
conda run -n py312 python -m pip install --no-index \
  --find-links /tmp/quant-m3-g0-py312-wheelhouse \
  --no-build-isolation -e '.[dev]' 'pyqlib==0.9.7'
```

不得让 py312 联网。若再缺任何构建依赖或需要其他 sdist，立即停止。

## 3. 探针与文件

安装成功后完整执行原环境任务书 §4 的 1–8 项，记录更新后的 wheelhouse 总 SHA、py312 package-list SHA、base
前后 package-list 完全一致性。base readiness 测试仍在 base；py312 测试必须披露排除一项。

项目内只新增 `docs/M3_G0_py312_Editables增量返工交付报告.md`；不得覆盖历史报告或修改代码、测试、配置、
路线图、P4C。保留 wheelhouse供独立复验。成功状态“待独立复验”，不得关闭 G0。
