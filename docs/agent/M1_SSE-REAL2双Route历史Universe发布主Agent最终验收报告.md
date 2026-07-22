# M1 SSE-REAL2 双 Route 历史 Universe 发布 — 主 Agent 最终验收报告

## 结论

- **SSE-REAL2 最终验收通过。**
- SH_CONNECT 与 SZ_CONNECT 的历史 universe 已按 reverse-audit 合同原子发布，可供按历史日期查询港股通可投资范围。
- 本结论仅覆盖 [`M1_SSE-REAL2双Route历史Universe发布任务单.md`](M1_SSE-REAL2双Route历史Universe发布任务单.md)，不等于 M1、M3、M4 或任一 Gate 整体完成。

## 职责分离证据

1. 外部执行：[`M1_SSE-REAL2双Route历史Universe发布执行报告.md`](M1_SSE-REAL2双Route历史Universe发布执行报告.md)
2. 不同全新外部会话独立验证：[`M1_SSE-REAL2双Route历史Universe发布独立验证报告.md`](M1_SSE-REAL2双Route历史Universe发布独立验证报告.md)
3. 主 Agent 于 2026-07-17 复核上述报告，并重新运行双 Route 零写入 dry-run。

## 主验结果

| 项目 | SH_CONNECT | SZ_CONNECT |
| --- | ---: | ---: |
| 发布行数 | 1062 | 1149 |
| 唯一证券数 | 919 | 1014 |
| coverage_start | 2014-11-17 | 2016-12-05 |
| 当前开放区间/2026-07-10 成员 | 644 | 644 |
| baseline 成员 | 268 | 417 |
| Schema / 区间不重叠 | 通过 | 通过 |
| preview 与发布逐字段一致 | 通过 | 通过 |
| baseline 前一日 fail closed | 通过 | 通过 |

主 Agent 复跑：

```bash
python -m quant.data.rebuild_connect_universe \
  --route SH_CONNECT --baseline-date 2014-11-17 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 268 --dry-run

python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --baseline-date 2016-12-05 \
  --mode reverse-audit --snapshot-date 2026-07-10 \
  --expected-baseline-count 417 --dry-run
```

两条命令均 exit 0，分别返回 `1062/919/644/PASS` 与 `1149/1014/644/PASS`，且 `published=false`。

独立验证额外覆盖了边界/随机日期的 reverse replay 交叉检查，以及 REMOVE→ADD 重开区间的缺口日语义，均无 mismatch。两个 universe 目标之外的 event/raw/snapshot/calendar 未发现变化，发布目录无临时文件残留。

## 剩余边界

- 工作区没有可用 Git 基线，无法用 Git diff 绝对证明执行窗口内全库无其他字节变化；现有 hash、mtime、目标终态和数据合同证据足以支持本任务结论。
- HISTORY-PILOT10 尚未执行；因用户准备迁移目录，本轮在 SSE-REAL2 主验后暂停。
