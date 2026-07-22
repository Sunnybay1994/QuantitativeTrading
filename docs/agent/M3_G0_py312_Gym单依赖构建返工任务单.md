# M3 G0：`gym` 单依赖离线构建返工任务单

日期：2026-07-15  
状态：主 Agent 已复核官方 PyPI 元数据；退回原 Terra Medium 实现会话

## 1. 权威证据与唯一例外

官方 PyPI JSON：

- `https://pypi.org/pypi/pyqlib/0.9.7/json`：`Requires-Python >=3.8.0`，存在
  `pyqlib-0.9.7-cp312-...manylinux2014_x86_64...whl`，依赖未固定版本的 `gym`；
- `https://pypi.org/pypi/gym/0.26.2/json`：`Requires-Python >=3.6`，只发布 `gym-0.26.2.tar.gz`，没有 wheel。

因此上轮失败是 wheel-only 与 `gym` 发行形态冲突，不是 Python 3.12 声明不兼容。本轮只允许对官方
`gym==0.26.2` sdist 做一次离线、本地、纯依赖 wheel 构建；Qlib 本体必须仍用官方 cp312 wheel，其他依赖仍
wheel-only。不得从源码构建 Qlib、VCS 包或任意其他 sdist。

## 2. 现有 Wheelhouse 自证

允许复用 `/tmp/quant-m3-g0-py312-wheelhouse`，前提是它仍为当前用户所有、0700、内容为空且无 symlink/hardlink/
非普通 entry；不满足即停止，不删除未知内容。

取得 base 前指纹。用 base pip 从官方 HTTPS 索引下载：

```bash
# 唯一允许的 sdist；no-deps
python -m pip download --dest /tmp/quant-m3-g0-py312-wheelhouse \
  --index-url https://pypi.org/simple --retries 10 --timeout 30 --no-cache-dir \
  --no-deps --no-binary=:all: 'gym==0.26.2'

# 构建工具只能是 wheel；不得安装到 base
python -m pip download --dest /tmp/quant-m3-g0-py312-wheelhouse \
  --index-url https://pypi.org/simple --retries 10 --timeout 30 --no-cache-dir \
  --only-binary=:all: --no-deps setuptools wheel
```

记录三个文件的名称、size、SHA-256；gym 文件必须精确为官方 sdist 名称，构建工具必须 `.whl`。

## 3. 在 `py312` 离线构建 gym wheel

只允许：

```bash
conda run -n py312 python -m pip install --no-index \
  --find-links /tmp/quant-m3-g0-py312-wheelhouse setuptools wheel
conda run -n py312 python -m pip wheel --no-index \
  --find-links /tmp/quant-m3-g0-py312-wheelhouse --no-build-isolation --no-deps \
  --wheel-dir /tmp/quant-m3-g0-py312-wheelhouse \
  /tmp/quant-m3-g0-py312-wheelhouse/gym-0.26.2.tar.gz
```

生成物必须是 `gym-0.26.2-py3-none-any.whl`（或等价合法 pure-Python tag）。记录 SHA 后，允许删除**仅本任务刚
下载且已核对 SHA 的** `gym-0.26.2.tar.gz`，使 wheelhouse 恢复 wheel-only；不得删除其他路径。

## 4. 完整目标 wheel 解析与安装

随后重新执行上轮目标下载，增加
`--find-links /tmp/quant-m3-g0-py312-wheelhouse`；仍带 `--only-binary=:all:`、CPython 3.12/ABI/platform、
官方 HTTPS index、包集合 `hatchling '.[dev]' 'pyqlib==0.9.7'`。若 pip 再要求任何其他 sdist，停止，不扩张例外。

成功后确认 wheelhouse 只有普通 `.whl`，生成排序逐文件 SHA 与总 SHA，再用原任务单的 `--no-index` 两条命令
离线安装，并完整执行原环境任务书 §4 的 1–8 项。

## 5. 文件与状态

base 只 download，前后 package-list 必须完全相同。项目内只新增
`docs/M3_G0_py312_Gym单依赖构建返工交付报告.md`；不得覆盖历史报告或修改代码/测试/配置/路线图/P4C。
保留 wheelhouse供独立复验。成功状态“待独立复验”，失败记录真实阻塞；均不得关闭 G0。
