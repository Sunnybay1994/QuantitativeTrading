# M3 G0：`py312` 离线 Wheelhouse 返工任务单

日期：2026-07-15  
状态：主 Agent 已定位版本环境 DNS 差异；退回原 Terra Medium 实现会话

前置证据：

- [`M3_G0_py312环境创建与兼容探针交付报告.md`](M3_G0_py312环境创建与兼容探针交付报告.md)
- [`M3_G0_py312环境网络重试交付报告.md`](M3_G0_py312环境网络重试交付报告.md)

## 1. 根因证据与边界

主 Agent 重复探测确认：同一 WSL 内 base Python 可把 `pypi.org` 解析为代理地址，`py312` Python 的
`socket.getaddrinfo` 稳定报 `EAI_AGAIN`；WSL `curl` 对官方 PyPI/清华均 HTTP 200。禁止修改 DNS、`/etc/hosts`、
代理、pip 全局配置或用 `--trusted-host` 绕过 TLS。

本轮用 base Python 的 pip **只下载目标 CPython 3.12 Linux wheel** 到独占临时目录，再由 `py312` 完全离线安装。
base 只执行 download，不安装/升级/卸载任何包；`py312` 不发起网络请求。不允许 sdist、VCS 或源码硬装 Qlib。

## 2. Wheelhouse

临时目录固定为 `/tmp/quant-m3-g0-py312-wheelhouse`。执行前若已存在则停止，不删除或复用未知内容；否则以当前
用户创建，权限 0700。

从项目根用 base 执行目标解析；允许根据 `pip download --help` 对 platform tag 做最小语法修正，但不得改变
目标 Python/ABI/only-binary/包集合：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pip download \
  --dest /tmp/quant-m3-g0-py312-wheelhouse \
  --index-url https://pypi.org/simple --retries 10 --timeout 30 --no-cache-dir \
  --only-binary=:all: --python-version 3.12 --implementation cp --abi cp312 \
  --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
  hatchling '.[dev]' 'pyqlib==0.9.7'
```

若任一依赖没有目标 wheel或解析失败，停止并报告；不得允许 source distribution。下载成功后，确认目录只有普通
`.whl` 文件、无 symlink/hardlink alias/非 wheel，并按文件名字典序生成逐文件 SHA-256 清单与总清单 SHA。

## 3. `py312` 离线安装

先取得 base package-list SHA。只允许：

```bash
/home/mabw/miniforge3/bin/conda run -n py312 python -m pip install \
  --no-index --find-links /tmp/quant-m3-g0-py312-wheelhouse hatchling
/home/mabw/miniforge3/bin/conda run -n py312 python -m pip install \
  --no-index --find-links /tmp/quant-m3-g0-py312-wheelhouse \
  --no-build-isolation -e '.[dev]' 'pyqlib==0.9.7'
```

安装日志必须证明 `--no-index`；不得让 py312 联网。若 editable build 仍尝试下载或缺 wheel，停止。

## 4. 探针与清理

成功后完整执行原环境任务书 §4 的 1–8 项，并额外记录 wheelhouse 清单 SHA。独立复验完成前保留 wheelhouse，只读
使用；主 Agent 最终验收后再决定清理，不由实现 Agent删除。

项目内只新增 `docs/M3_G0_py312离线Wheelhouse返工交付报告.md`。不得覆盖前置报告、修改代码/测试/配置/路线图/
P4C 或关闭 G0。成功状态“待独立复验”；失败则保留真实阻塞。独立复验报告仍使用
`docs/M3_G0_py312环境创建与兼容探针独立复验报告.md`。
