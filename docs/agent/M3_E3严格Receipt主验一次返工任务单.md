# M3 E3 严格 Receipt 主验一次返工任务单

日期：2026-07-13  
状态：**已通过**；外部实现与独立复验闭环完成，主 Agent 最终验收通过  
原实现：[`M3_E3严格Receipt增量返工交付报告.md`](M3_E3严格Receipt增量返工交付报告.md)  
原独立复验：[`M3_E3严格Receipt独立初验报告.md`](M3_E3严格Receipt独立初验报告.md)  
权威合同：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.9  
返工交付：[`M3_E3严格Receipt主验一次返工交付报告.md`](M3_E3严格Receipt主验一次返工交付报告.md)  
独立复验：[`M3_E3严格Receipt主验一次返工独立复验报告.md`](M3_E3严格Receipt主验一次返工独立复验报告.md)  
最终验收：[`M3_E3严格Receipt主Agent最终验收报告.md`](M3_E3严格Receipt主Agent最终验收报告.md)

## 1. 结论与范围

R1–R4 正常路径与既有反例暂不回退，但主验发现临时 receipt I/O 失败语义未闭合，因此 E3 尚不能通过。
本轮只允许外部实现 Agent 修改：

```text
src/quant/research/m3/run_state.py
tests/unit/test_m3_run_state.py
docs/M3_E3严格Receipt主验一次返工交付报告.md
```

不得修改其他生产代码、既有报告、SSOT、路线图、G1/B2A/G8/G9；不得联网或访问 `_old/`、凭据。

## 2. P0：原始临时 I/O 异常泄露绝对路径

### 现象

`publish_stage_receipt` 在 `tempfile.mkstemp`、`os.fdopen`、临时文件 write/flush/fsync 和 cleanup 的部分分支
直接放出原始 `OSError`。主验最小复现令 `mkstemp` 抛出：

```text
PermissionError: [Errno 13] denied: '/tmp/e3-main-audit-.../PRIVATE/temp'
```

`str(exc)` 已包含绝对路径，违反严格脱敏合同；仅搜索源码中的 `raise ... from exc` 无法发现标准库直接抛出。

### 根因与规则

对外错误边界只覆盖了显式 catch/re-raise，没有覆盖临时 I/O 调用本身。公开 publish 的所有本地 I/O 失败
都必须转换为稳定 `ValueError`，使用 `from None`，且 `str/__cause__/traceback` 不得包含 receipt/root/temp
绝对路径。禁止因此回退 `os.replace`。

### 必须实现

- `mkstemp` 失败：稳定报“receipt 临时文件创建失败”；
- fd 接管、write、flush、文件 fsync 失败：稳定报“receipt 临时文件写入失败”；
- 非 `FileExistsError` 的 link 仍报“receipt 原子创建失败”；
- temp cleanup 失败：稳定报“receipt 临时文件清理失败”；
- 目录 open/fsync/close 失败：稳定报“父目录 fsync 失败”；只保留既有 unsupported errno 白名单；
- 所有分支关闭已取得 fd，不新增 fd/temp 泄漏；异常链与 traceback 脱敏。

## 3. P1：发布成功后 cleanup 失败被静默吞掉

### 现象

当前 finally 只有 `primary_error is None and not published` 才重新抛 cleanup 错误。主验在 link/fsync 成功后
令临时 `Path.unlink` 失败，函数仍返回成功，同时遗留：

```text
.receipt.json.<random>.tmp
```

### 根因与规则

“cleanup 不得掩盖主异常”不等于“cleanup 可以静默失败”。固定语义：

- 已有主异常：cleanup 失败不得覆盖主异常；
- 没有主异常：cleanup 失败必须以稳定脱敏错误失败，不论 receipt 是否已经 link 成功；
- receipt 已发布后发生 cleanup/目录 fsync 失败时不得删除或覆盖 receipt；重试必须严格验真后复用；
- 不得用 `Path.exists()` 把不可读/权限错误误当成“不存在”。

## 4. P1：目录 fd close 不得掩盖 fsync 主异常

`_fsync_parent_dir` 的 `os.close(fd)` 位于 finally，若 fsync 与 close 同时失败，close 的原始异常可能覆盖已
脱敏的 fsync 主异常。必须应用同一优先级：主异常优先；无主异常时 close 失败以稳定“父目录 fsync 失败”
暴露。unsupported fsync 后若 close 失败，不得把 close 当作 unsupported 静默忽略。

## 5. P2：scope 错误类型应是稳定契约错误

`StageReceipt.__post_init__`、JSON parser 与 `publish_stage_receipt` 当前对 list/dict scope 执行 frozenset
membership，可能抛原始 `TypeError: unhashable type`。先检查 `type(scope) is str`，统一抛稳定 `ValueError`；
不得放宽合法 scope 集合。

## 6. 必测反例

至少新增以下测试，测试失败注入不得污染真实项目目录：

1. `mkstemp` 抛含绝对路径的 `PermissionError`；
2. fd 接管或 temp write/flush/fsync 抛含绝对路径的 `OSError`，同时确认 fd/temp 被清理；
3. link 成功、目录 fsync 成功、temp unlink 失败：不得返回成功；receipt 保留有效；错误脱敏；清理测试残留；
4. link 主异常 + unlink cleanup 双失败：原子创建主异常优先，cleanup 不覆盖；
5. 目录 fsync 主异常 + close 双失败：fsync 主异常优先；仅 close 失败时稳定失败；
6. `FileExistsError` 同内容复用成功 + temp cleanup 失败：不得伪装复用成功；
7. direct constructor、JSON 和 publish 的 scope 为 list/dict：全部稳定 `ValueError`；
8. 上述异常逐一断言 `str/__cause__/traceback` 不含注入的绝对路径；生产路径仍无 `os.replace`。

## 7. 验证与交付

外部实现 Agent 必须在 WSL Miniforge base 执行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest tests/unit/test_m3_run_state.py -q
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_run_state.py tests/unit/test_m3_contracts.py tests/unit/test_m3_snapshot.py -q
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

报告写入 `docs/M3_E3严格Receipt主验一次返工交付报告.md`，逐项记录文件状态、异常优先级、测试数字和
限制，不得宣称主验/E3/M3/Gate 通过。

返工完成后必须交给未参与本轮编码的外部初验 Agent 独立复验；复验报告命名：

```text
docs/M3_E3严格Receipt主验一次返工独立复验报告.md
```

只有该复验通过，才重新交主 Agent 终验。
