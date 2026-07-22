# M3 E3 严格 Receipt 主验一次返工独立复验报告

日期：2026-07-13  
复验角色：未参与本轮编码的外部独立复验 Agent  
工作目录：`/home/mabw/win/Cursor/quant`  
验收清单：[`M3_E3严格Receipt主验一次返工任务单.md`](M3_E3严格Receipt主验一次返工任务单.md)  
实现线索（不作证明）：[`M3_E3严格Receipt主验一次返工交付报告.md`](M3_E3严格Receipt主验一次返工交付报告.md)  
契约：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.9  
代码：`src/quant/research/m3/run_state.py`、`tests/unit/test_m3_run_state.py`

**结论：独立复验通过，可交主 Agent 终验。**  
本报告不宣称主验 / E3 / M3 / 任何 Gate 通过。

---

## P0 / P1 / P2 关闭证据

### P0：临时 I/O 原始异常泄露绝对路径 — 关闭

独立对抗（`/tmp`，非实现者单测）：

| 注入点 | 结果 |
|---|---|
| `tempfile.mkstemp` → 含绝对路径 `PermissionError` | 稳定 `ValueError("receipt 临时文件创建失败")`；`str/__cause__/traceback` 无注入绝对路径 |
| `os.fdopen` → 含绝对路径 `OSError` | 稳定「写入失败」；fd 已关；temp 已清 |
| `handle.write` → 含绝对路径 `OSError`（实现者未覆盖的 write 路径） | 稳定「写入失败」；fd/temp 清理 |

生产路径静态确认：无 `os.replace`。

### P1：发布成功后 cleanup 失败被静默 — 关闭

| 场景 | 结果 |
|---|---|
| link + 目录 fsync 成功后 temp `unlink` 失败 | 不得返回成功；稳定「临时文件清理失败」；receipt 保留且 `verify_stage_receipt` 通过；错误脱敏 |
| link 主异常 + unlink 双失败 | 稳定「原子创建失败」优先；cleanup 不覆盖 |
| `FileExistsError` 同内容复用成功 + cleanup 失败 | 不得伪装复用成功；稳定「清理失败」；已发布 receipt 字节与验真不变 |

额外对抗：link 成功后目录 fsync 失败 + unlink 失败 → 「父目录 fsync 失败」优先；receipt 保留。

### P1：目录 fd close 不得掩盖 fsync — 关闭

直接调用 `_fsync_parent_dir`：

- fsync + close 双失败 → 「父目录 fsync 失败」，脱敏，fsync 转换优先  
- 仅 close 失败 → 稳定「父目录 fsync 失败」  
- unsupported fsync（`EINVAL`）后 close 失败 → 不得静默，稳定失败  

### P2：scope 错误类型 — 关闭

`scope=list/dict` 时：`StageReceipt` 构造、`publish_stage_receipt`、JSON/`verify_stage_receipt` 均为稳定 `ValueError("非法 scope...")`，非 `TypeError`。

### 静态：对外 OSError 转换 raise 均为 `from None` — 关闭

AST 扫描 `run_state.py` 中 `except OSError`（及同类）分支内构造的 `ValueError`：全部为 `from None`；未发现 `from <non-None>`。

---

## 额外对抗结果（实现者测试之外）

全部在 `/tmp` 执行，结束后清理；**未修改**生产代码与既有测试。

1. mkstemp 含绝对路径 `PermissionError` → 通过  
2. write / fdopen `OSError` → 「写入失败」+ fd/temp 清理 → 通过  
3. link 成功后 unlink 失败 → 不成功返回；receipt 可验真 → 通过  
4. link + unlink 双失败 → 主异常优先 → 通过  
5. 目录 fsync/close 双失败、仅 close、unsupported+close → 通过  
6. 复用成功 + cleanup 失败 → 不得伪装成功 → 通过  
7. scope list/dict 三路径 ValueError → 通过  
8. 生产源码无 `os.replace` → 通过  
9. 静态 `from None` → 通过  
10. （额外）link 后目录 fsync 失败 + unlink 失败 → fsync 优先、receipt 保留 → 通过  

对抗脚本结果：`RESULT: ALL ADVERSARIAL PASSED`。

---

## 命令与数字（WSL Miniforge base，`PYTHONPATH=src`）

```text
pytest tests/unit/test_m3_run_state.py -q
60 passed

pytest tests/unit/test_m3_run_state.py tests/unit/test_m3_contracts.py tests/unit/test_m3_snapshot.py -q
86 passed

pytest -q
486 passed

ruff check src tests
All checks passed!

mypy src
Success: no issues found in 72 source files
```

---

## 已知限制

- 单个 receipt 原子发布 ≠ 多 artifact 跨文件事务；外部 TOCTOU 仍依赖再次验真 fail-closed。  
- Symlink/hardlink 相关行为依赖 `/tmp` 原生 Linux FS。  
- 未勾选路线图 G0–G9；未宣称主验 / E3 / M3 / Gate 通过。

## 未关闭问题

无。

---

**独立复验通过，可交主 Agent 终验。**
