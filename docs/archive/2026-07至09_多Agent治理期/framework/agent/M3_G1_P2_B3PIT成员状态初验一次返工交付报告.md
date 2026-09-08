# M3 G1-P2 B3：独立初验 P1-1 一次返工交付报告

日期：2026-07-14  
角色：外部实现 Agent（原 G1-P2 B3 实现者；本轮仅返工）  
实际模型标识：`cursor-grok-4.5-high`  
状态：**待独立复验**  
返工任务：[`M3_G1_P2_B3PIT成员状态初验一次返工任务单.md`](M3_G1_P2_B3PIT成员状态初验一次返工任务单.md)  
不通过证据：[`M3_G1_P2_B3PIT成员状态独立初验报告.md`](M3_G1_P2_B3PIT成员状态独立初验报告.md)  
原交付：[`M3_G1_P2_B3PIT成员状态交付报告.md`](M3_G1_P2_B3PIT成员状态交付报告.md)

**本报告不宣称 B3 / P2 / G1 / Gate 完成。** 仅关闭主 Agent 已确认的 **P1-1**。

## 1. 修改文件

| 文件 | 改动 |
|---|---|
| `src/quant/data/index_membership.py` | `ObservedMembershipResult.__post_init__`：先验证三表，再 `object.__setattr__` 写回 validator 返回 frame，最后仅基于公开 frame 重算并比较三 digest；`_validate_eligible_frame` 对可 coercion 的 `as_of`/`symbol` 规范化到 `Date`/`Utf8`，List/Struct 仍 fail-closed |
| `tests/unit/test_index_membership.py` | 新增 P1-1 回归：单表/三表 Utf8 coercion 写回自洽；List/Struct 拒绝且 `__cause__ is None`；既有 drift/verify 路径保留 |
| `docs/M3_G1_P2_B3PIT成员状态初验一次返工交付报告.md` | 本返工交付报告 |

未修改：`m3_identity.py`、领域 Schema、包根导出、原交付/初验报告、配置、路线图、Gate；未联网；未读 token/`_old/`。

## 2. 三表 write-back 顺序

```text
1. observations = IndexConstituentObservationSchema.validate(...) 消费返回值
2. membership   = UniverseMembershipSchema.validate(...) 消费返回值
3. eligible     = _validate_eligible_frame(...) 消费规范化返回值
4. object.__setattr__ 依次写回 observations / membership / eligible_keys
5. 仅对 self.observations / self.membership / self.eligible_keys
   调用 clean_table_content_sha256，与公开 digest 字段比较
```

冻结设计为**成功构造并规范化写回**（非拒绝可合法 coercion 的输入）：公开 `observation_date` / `effective_*` / `as_of` 为 `pl.Date`，且公开表重算 digest 与字段立即相等。

## 3. 验证数字

环境：WSL Miniforge `base`，`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`PYTHONPATH=src`。

| 命令 | 结果 |
|---|---|
| 定向 pytest（membership/identity/backfill/mappers） | **168 passed** |
| 全量 `pytest -q` | **562 passed** |
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: no issues found in 75 source files |
| `test_index_membership.py` 测试函数数 | **19**（原 17 + P1-1 回归 2） |
| `test_m3_identity.py` | **6**（未改） |

## 4. 未实现 / 边界

- 仅处理 P1-1；不扩大到 P3/P4。
- eligible 无独立领域 Schema；规范化仍在 `_validate_eligible_frame` 内完成，不复制 Schema SSOT。
- 独立复验与主 Agent 终验、路线图/Gate 更新均不在本轮。

## 5. 下一步

等待**未参与本轮实现**的独立复验 Agent 出具  
[`M3_G1_P2_B3PIT成员状态初验一次返工独立复验报告.md`](M3_G1_P2_B3PIT成员状态初验一次返工独立复验报告.md)。  
复验通过前不得交主 Agent 终验，不得宣称 P2/G1/Gate 通过。
