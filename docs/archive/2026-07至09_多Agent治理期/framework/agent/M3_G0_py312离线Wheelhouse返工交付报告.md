# M3 G0：`py312` 离线 Wheelhouse 返工交付报告

日期：2026-07-15  
状态：**阻断：`pyqlib==0.9.7` 的 CPython 3.12 依赖缺少目标 wheel**

## 1. 执行范围

确认 `/tmp/quant-m3-g0-py312-wheelhouse` 不存在后，以权限 `0700` 创建该独占目录。复用既有 `py312`
（`Python 3.12.13`），未改 DNS、`/etc/hosts`、代理、pip 配置或 base 包集合；未运行 py312 离线安装和后续探针。

base package-list 原始 SHA-256 在下载前后均为：

`568106ba05556241e105fab9b7ce4712a5a5ff4680f87c3160f4f1ab0750d750`

base canonical SHA-256 在下载前后均为：

`77329bcb2c14db6cd2925053f4bde047969a3c100cab7b53f0fc192b8de57e78`

## 2. Wheel 下载结果

从项目根使用任务书冻结的 base `pip download` 命令、官方 HTTPS index、`--only-binary=:all:`、目标
CPython 3.12 / `cp312` / manylinux 参数执行下载，退出码为 `1`。

官方索引可访问，解析已取得 `pyqlib-0.9.7` 的 CPython 3.12 wheel 元数据；但其依赖 `gym` 对目标 Python
无可用 wheel。pip 明确排除 `gym` 的可见发行版本，原因均为 `Requires-Python <3.12`，最终报：

```text
Could not find a version that satisfies the requirement gym (from pyqlib)
No matching distribution found for gym
```

这是目标 Python/ABI 的依赖解析失败，不允许以 sdist、VCS、源码安装或放宽 `--only-binary` 继续。

## 3. 失败后状态

- wheelhouse 权限与所有者：`700 mabw mabw`。
- wheel 文件数、其他普通文件数、symlink 数均为 `0`；没有生成可供校验或离线安装的完整 wheelhouse。
- 未执行两条 `--no-index` py312 安装命令，未改 py312 包集合。
- 未执行 `pip check`、pyqlib License/版本、Qlib/Alpha158/LGBModel import、readiness、py312 定向测试或
  base 全文件测试。
- 未修改项目代码、测试、配置、路线图、P4C 或任何既有报告；G0 仍未通过。

## 4. 下一步

该问题是 `pyqlib==0.9.7` 的目标 Python 3.12 依赖闭包与 wheel-only 约束冲突。应由主 Agent 复核官方发行
元数据和 Qlib 支持口径，再决定是否修订权威兼容性决策；不得由实现会话改用 source、VCS、非任务书依赖或
删除现有 wheelhouse。
