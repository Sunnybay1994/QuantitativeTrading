# M3 G0：`editables` wheel 增量返工交付报告

日期：2026-07-15  
实现会话：原 Terra Medium 外部实现会话  
状态：待独立复验

## 1. 范围与结论

本轮只在既有 WSL Miniforge `py312` 隔离环境中补齐 Hatchling PEP 660 所需的
`editables==0.6` wheel，并完全离线重试项目 editable 安装和 `pyqlib==0.9.7` 安装。
未修改 `base`、项目代码、测试、配置、路线图、P4C 或历史报告；项目内唯一新增本报告。

安装成功，未再出现新的构建依赖缺口或 sdist 请求。`py312` 完成规定运行时探针及定向测试；
`base` 既有 readiness 回归也通过。此结果只表示 `py312` 环境探针待独立复验，G0 尚未关闭。

## 2. wheelhouse 边界与唯一增量

安装前自证 `/tmp/quant-m3-g0-py312-wheelhouse`：

- 目录权限/属主：`700:mabw:mabw`；
- 普通 wheel：206；非 `.whl` 普通文件：0；symlink：0；硬链接 alias：0；
- 排序 wheel 清单总 SHA-256：
  `55f9b398fd56b1ff5111b7c3f0fa0dafb7d222a37e7d1067d5de223d6993051c`，
  与任务书冻结值一致。

仅用 WSL `base` 的 pip 从官方 HTTPS index 下载、未安装：

```bash
python -m pip download --dest /tmp/quant-m3-g0-py312-wheelhouse \
  --index-url https://pypi.org/simple --retries 10 --timeout 30 --no-cache-dir \
  --only-binary=:all: --no-deps 'editables==0.6'
```

新增文件为 `editables-0.6-py3-none-any.whl`，size `5438` bytes，SHA-256：
`d70e4698078a1d033e7786d9c64e5be070d058a67c21417024d38a58ac20aa43`。
下载后非 `.whl` 普通文件仍为 0，未下载 sdist。

最终 wheelhouse 为 207 个普通 `.whl`，非 wheel：0、symlink：0、硬链接 alias：0；
排序 wheel 清单总 SHA-256：
`f306f9c9226a2b97d31f0118524479e5e0128ccd4e45823009393bed6daab6cd`。
wheelhouse 保留供独立复验。

## 3. 离线安装

`py312` 只使用 `--no-index --find-links` 执行：

```bash
conda run -n py312 python -m pip install --no-index \
  --find-links /tmp/quant-m3-g0-py312-wheelhouse 'editables==0.6'
conda run -n py312 python -m pip install --no-index \
  --find-links /tmp/quant-m3-g0-py312-wheelhouse \
  --no-build-isolation -e '.[dev]' 'pyqlib==0.9.7'
```

两条命令均 exit 0。第二条成功构建 editable `quant-0.1.0` wheel 并安装
`pyqlib-0.9.7`；未联网、未要求额外构建依赖或 sdist。

## 4. 原环境任务书 §4 探针

| 项目 | 结果 |
|---|---|
| `conda run -n py312 python --version` | exit 0；`Python 3.12.13` |
| `python -m pip check` | exit 0；`No broken requirements found.` |
| `importlib.metadata` | `pyqlib=0.9.7`；其发行元数据 `License` 字段为 `None` |
| 关键 import | exit 0；`qlib 0.9.7`、`Alpha158`、`LGBModel` 均可离线导入 |
| readiness 函数 | `PYTHONPATH=src` 下 `_check_python_version(">=3.8,<3.13")` 与 `_check_qlib_importable()` 均返回 `[]` |
| `py312` 定向测试 | exit 0；`41 passed, 1 deselected`，执行了 `-k 'not fixture_data_surfaces_python_or_qlib_runtime_errors'` |
| `base` 完整 readiness 测试 | exit 0；`42 passed` |

`py312` 的关键模块版本：`qlib 0.9.7`、`lightgbm 3.3.5`、`mlflow 3.14.0`。

Qlib 导入和测试期间出现 NumPy `longdouble` 平台支持 warning，以及 Qlib 对未安装的可选
CatBoost、XGBoost、PyTorch 模型的提示；三者均未导致退出码非零，且不属于本任务冻结的依赖范围。

## 5. base 不变性

本轮前后 `conda list -n base --json | sha256sum` 均为：

```text
568106ba05556241e105fab9b7ce4712a5a5ff4680f87c3160f4f1ab0750d750
```

以排序、紧凑 JSON 序列化后的规范 SHA-256 前后也均为：

```text
77329bcb2c14db6cd2925053f4bde047969a3c100cab7b53f0fc192b8de57e78
```

因此 base package list 前后完全一致。

`py312` 最终 `conda list -n py312 --json` SHA-256：

```text
bdd3efda7398ceb98339e8b39deef3c67f42506d0a9c8257773d0c4cb4ef19b1
```

## 6. 复验交接

独立复验应在全新会话中只读重跑 §4 的探针和测试，并核对：

1. `py312` 位于 WSL Miniforge 且仍是 CPython 3.12；
2. wheelhouse 的 207 wheel、物理边界及总 SHA；
3. `base` 前后指纹未变化；
4. 本报告中披露的 `py312` 定向测试排除了一个 base 未就绪环境专用断言，不能误述为全文件通过。

G0 仍受后续真实数据、provider 与长期数据门禁约束，本报告不构成 G0 关闭依据。
