# M1 SSE-E3 历史资格逆向审计工具独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（全新会话，未参与实现；模型 cursor-grok-4.5-high）  
任务单：[M1_SSE-E3历史资格逆向审计工具任务单.md](M1_SSE-E3历史资格逆向审计工具任务单.md)  
交付报告：[M1_SSE-E3历史资格逆向审计工具交付报告.md](M1_SSE-E3历史资格逆向审计工具交付报告.md)  
前置主验：[M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md](M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md)、[M1_SSE-E2单RouteClean事件原子重建主Agent最终验收报告.md](M1_SSE-E2单RouteClean事件原子重建主Agent最终验收报告.md)

**结论：初验通过（exit 0）。** 生产代码/实现测试/README/配置/data 严格只读；未联网、未访问项目 `data/`、未跑全量 pytest、未做 Git。不宣称真实历史覆盖已发布，不宣称 Gate 通过。

## 1. 范围与纪律

| 项 | 状态 |
|---|---|
| 唯一写入 | 本报告 |
| 生产代码/实现测试/README/配置 | 只读 |
| 项目 `data/` / 网络 / 全量 pytest / Git | 未触碰 |
| 环境 | WSL Miniforge `base`（`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`） |
| 对抗工作区 | `/tmp/m1_sse_e3_adversarial.py`、`/tmp/m1_sse_e3_adv/` |

## 2. 合同逐项核对

| # | 冻结合同点 | 证据 | 结论 |
|---|---|---|---|
| 1 | 值对象自证：`VerifiedReverseEligibilityAudit` frozen/slots，构造重算不变量，调用者不得自报成功 | `eligibility.py` `__post_init__` 重算 route/date/count/排序/去重/event 窗；伪造 reverse_count 与 symbols 长度不一致 → `REVERSE_AUDIT_COUNT_MISMATCH`（`/tmp` 探针） | 通过 |
| 2 | `verify_reverse_eligibility_history`：Schema + exact dtype；route 仅 SH/SZ；snapshot 单 route/单日且全 `buy_eligible=True`；`snapshot_date>baseline` | `_require_exact_dtypes_*` + Schema validate；bool/int、datetime/date、非法 route 单测；越界 coverage 码 | 通过 |
| 3 | reverse 状态机：按 `effective_date,symbol` 逆序；逆 ADD 须 active 后删；逆 REMOVE 须 inactive 后加；矛盾 `STATE_CONFLICT`；同日冲突 `EVENT_CONFLICT` | `_verify_reverse_eligibility_history` 循环；实现 STATE/EVENT 冲突单测 | 通过 |
| 4 | 完整 coverage：全部事件须 baseline 严格小于 effective_date 且不超过 snapshot；越界不得静默过滤 → `COVERAGE_INVALID` | 实现单测仅覆盖孤立越界；本初验在完整合法事件集上插入早于/等于 baseline、晚于 snapshot（见第4节）均 `COVERAGE_INVALID` | 通过 |
| 5 | 最终规模等于 expected；返回排序 baseline_symbols 与 counts/min/max；SH→268 / SZ→417 fixture；行序无关 | SH/SZ fixture 与 row-order 单测；count mismatch 码 | 通过 |
| 6 | 稳定脱敏码：五码经 `EligibilityHistoryError`；异常不含 symbol/path/raw | 五码 frozenset；脱敏单测；对抗错误串无路径与证券号 | 通过 |
| 7 | 精确只读 reader：`read_route_date` / `read_route`；精确路径；root/祖先/route/date/target symlink、FIFO、目录、缺失 fail-closed；不跟随外部 | `_assert_safe_clean_read_target` + guarded read；storage 9 项 + `/tmp` 五类 symlink 外部字节/mtime 不变 | 通过 |
| 8 | CLI 严格 JSON/只读：成功单行 JSON（无 symbols/path）；失败非零且无成功 JSON；不写 artifact/不联网 | `audit_connect_eligibility.main`；成功/失败单测；`/tmp` COUNT_MISMATCH：stdout 空、stderr 稳定码、code=1 | 通过 |
| 9 | 导出与文档：`quant.data` 仅导出值对象/纯函数；README 只读审计命令 | `__init__.py`；README 明确不发布/不写 artifact | 通过 |

## 3. 定向验证（任务单四项）

```text
python -m pytest tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py -q
  → 18 passed                 exit 0

python -m pytest tests/unit/test_storage.py -q -k 'connect and read'
  → 9 passed, 20 deselected   exit 0

ruff check <白名单源与测试>
  → All checks passed!        exit 0

mypy src/quant/data/eligibility.py src/quant/data/storage.py src/quant/data/audit_connect_eligibility.py
  → Success: no issues found  exit 0
```

合计：`EXITS pytest_elig=0 pytest_storage=0 ruff=0 mypy=0`。

## 4. 实现者未公开对抗（WSL `/tmp`）

相对交付报告与实现单测，本初验新增：

### 4.1 完整合法事件集 + 越界插入（须 COVERAGE_INVALID，禁止静默过滤）

合法基线：8 只 → ADD1 + REMOVE1 → snapshot 仍 8；单独逆推 PASS。再向同一完整合法事件集分别追加：

| ID | 反例 | 期望 | 结果 |
|---|---|---|---|
| C1 | 插入 effective_date = baseline - 1 day | `REVERSE_AUDIT_COVERAGE_INVALID`，不得 PASS | PASS |
| C2 | 插入 effective_date = baseline（等于边界，合同要求严格大于） | 同上 | PASS |
| C3 | 插入 effective_date = snapshot + 1 day | 同上 | PASS |

实现者单测 `test_event_before_baseline_not_silently_filtered` 仅含孤立越界事件；C1–C3 在完整合法集合上插入，排除“先过滤再逆推成功”路径。

### 4.2 reader symlink 攻击（外部字节/mtime 不变）

| ID | 反例 | 期望 | 结果 |
|---|---|---|---|
| S1 | 目标 data.parquet → 外部 symlink | fail-closed；外部 EXT_TARGET_MARKER_E3 不变 | PASS |
| S2 | route=SH_CONNECT 目录 symlink | fail-closed；外部不变 | PASS |
| S3 | snapshot date=... 目录 symlink | fail-closed；外部不变 | PASS |
| S4 | store root 本身为 symlink | fail-closed；外部 sentinel 不变 | PASS |
| S5 | root 祖先目录为 symlink | fail-closed；外部与真实 parquet 不变 | PASS |

```text
coverage: C1-C3 PASS
symlink: S1-S5 PASS
ALL_ADVERSARIAL_PASS  exit 0
```

补充探针：伪造 VO → COUNT_MISMATCH；CLI 有空事件 parquet + expected=9 → code=1、stdout 空、stderr=`REVERSE_AUDIT_COUNT_MISMATCH`。

## 5. 已知非阻塞备注（不构成初验失败）

- `_validate_controlled_root` 错误文案仍写“受控 raw root”，clean reader 复用时文案略偏，fail-closed 行为正确（与 E2 初验备注同类）。
- 事件文件缺失时 CLI 将 storage ValueError 映射为 `REVERSE_AUDIT_INPUT_INVALID`（而非业务 COUNT 码）；属缺文件路径，仍 fail-closed 且无成功 JSON。
- 合成 fixture 268/417 仅证算法合同；真实端点逆推证据仍以 E1 主验为准。现有项目 clean 若仍含旧 mapper 错误 action，真实审计可能 STATE_CONFLICT——属 E2 授权 replace 后事项，不降级本包代码合同。

## 6. 初验判定

- **初验：通过**
- **综合退出码：0**
- 返工项：无
- 下一步：交主 Agent 终验；不得由本报告勾选路线图或宣称真实历史覆盖已发布。
