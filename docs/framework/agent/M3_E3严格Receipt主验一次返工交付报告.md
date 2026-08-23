# M3 E3 严格 Receipt 主验一次返工交付报告

执行范围：[`M3_E3严格Receipt主验一次返工任务单.md`](M3_E3严格Receipt主验一次返工任务单.md)  
契约 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.9  
日期：2026-07-13

**本报告不宣称主验 / E3 / M3 / 任何 Gate 通过。**  
状态：`待独立复验`（实现 Agent 自测通过；须交未参与本轮编码的外部初验 Agent 复验，报告名：`docs/M3_E3严格Receipt主验一次返工独立复验报告.md`）。

---

## 修改文件

| 文件 | 变更 |
|---|---|
| `src/quant/research/m3/run_state.py` | P0/P1/P2 临时 I/O 脱敏、cleanup/close 优先级、scope 类型门禁 |
| `tests/unit/test_m3_run_state.py` | 必测反例 1–8（monkeypatch + `/tmp` 原生 FS） |
| `docs/M3_E3严格Receipt主验一次返工交付报告.md` | 本报告 |

未修改其他生产代码、既有报告、SSOT、路线图、G1/B2A/G8/G9；未联网；未触碰 `_old/` / 凭据。生产路径仍无 `os.replace`。

---

## P0：临时 I/O 原始 OSError → 稳定脱敏 ValueError

公开 `publish_stage_receipt` 本地临时 I/O 失败一律 `ValueError` + `from None`；`str/__cause__/traceback` 不含绝对路径。

| 失败点 | 稳定消息 |
|---|---|
| `tempfile.mkstemp` | `receipt 临时文件创建失败` |
| `os.fdopen` / write / flush / 文件 `fsync` | `receipt 临时文件写入失败` |
| 非 `FileExistsError` 的 `os.link` | `receipt 原子创建失败` |
| temp `unlink` cleanup | `receipt 临时文件清理失败` |
| 目录 open / fsync / close | `父目录 fsync 失败`（仅保留 `EINVAL/ENOTSUP/EOPNOTSUPP` 白名单） |

fd 接管失败时主动 `os.close` 已取得 fd；所有分支 finally 清理 temp，不新增 fd/temp 泄漏。禁止 `os.replace`。

---

## P1：cleanup 失败不得静默；异常优先级

固定语义：

1. **已有主异常**：cleanup 失败不得覆盖主异常（例如 link 失败优先于 unlink 失败）。
2. **无主异常**：cleanup 失败必须以稳定「receipt 临时文件清理失败」失败，**不论 receipt 是否已 link / 复用成功**。
3. receipt 已发布后 cleanup / 目录 fsync 失败：不删除、不覆盖已发布 receipt；重试走严格验真复用。
4. cleanup 使用 `unlink` + `FileNotFoundError` 忽略；**不用** `Path.exists()`，避免权限错误被当成不存在。

---

## P1：目录 fd close 不得掩盖 fsync 主异常

`_fsync_parent_dir`：

- 主异常（已脱敏的 fsync/`ValueError`）优先；close 失败不覆盖。
- 无主异常时 close 失败 → 稳定「父目录 fsync 失败」。
- unsupported fsync（白名单 errno）后若 close 失败，不得当 unsupported 静默忽略。

---

## P2：非法 scope → 稳定 ValueError

新增 `_require_scope`：先 `type(scope) is str`，再 membership。  
用于 `StageReceipt.__post_init__`、JSON parser、`publish_stage_receipt`。  
list/dict 等不可哈希类型不再抛 `TypeError: unhashable`；合法 scope 集合未放宽。

---

## 必测反例覆盖（任务单 §6）

| # | 用例 | 断言要点 |
|---|---|---|
| 1 | `mkstemp` → 含绝对路径 `PermissionError` | 稳定创建失败；脱敏 |
| 2 | `fdopen` / 文件 `fsync` → 含绝对路径 `OSError` | 写入失败；fd 已关；temp 已清；脱敏 |
| 3 | link+目录 fsync 成功后 temp unlink 失败 | 不得返回成功；receipt 可验真；脱敏；清残留 |
| 4 | link 主异常 + unlink 双失败 | 原子创建优先；cleanup 不覆盖 |
| 5 | 目录 fsync+close 双失败；仅 close；unsupported fsync 后 close | 主异常优先；close 单独失败稳定报错 |
| 6 | `FileExistsError` 同内容复用 + cleanup 失败 | 不得伪装复用成功 |
| 7 | constructor / JSON / publish 的 list/dict scope | 全部稳定 `ValueError` |
| 8 | 上述异常 + 源码 | `str/__cause__/traceback` 无注入绝对路径；无 `os.replace` |

---

## 验证数字（WSL Miniforge base，`PYTHONPATH=src`）

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

## 限制与未宣称项

- 未实现 DAG / CLI / MLflow / acceptance；未勾选路线图 G0–G9。
- 单个 receipt 原子发布 ≠ 多 artifact 跨文件事务；外部 TOCTOU 仍由再次验真 fail-closed。
- Symlink/hardlink 相关单测依赖 `/tmp` 原生 Linux FS。
- **不得将本报告解读为主验 / E3 / M3 / Gate 通过**；下一步为独立复验。

## 合同矛盾

本轮未发现任务单与 §4.9 合同冲突；未放宽任何契约。
