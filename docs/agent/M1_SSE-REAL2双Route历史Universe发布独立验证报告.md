# M1 SSE-REAL2 双 Route 历史 Universe 发布 — 独立验证报告

## 结论

- **独立验证：通过**
- 角色：未参与执行的外部独立验证 Agent（全新会话）；代码/data/配置严格只读
- 唯一写入：本报告
- **不宣称**主验、Gate 或里程碑完成；交主 Agent 终验

## 验证环境

- 工作目录：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`
- Python：`/home/mabw/miniforge3/bin/conda run -n base`
- 网络：未联网；未读取/输出 token；未运行全量 pytest；未执行 rebuild/update/publish（仅 `--dry-run`）

## 依据

- 任务书：`docs/agent/M1_SSE-REAL2双Route历史Universe发布任务单.md`
- 执行报告：`docs/agent/M1_SSE-REAL2双Route历史Universe发布执行报告.md`
- SSE-REAL1 主验：`docs/agent/M1_SSE-REAL1真实SHClean事件重建主Agent最终验收报告.md`
- 契约：`UniverseMembershipSchema`、`eligible_symbols_on`、`rebuild_connect_universe` dry-run

---

## 验收映射（任务书第 3 节）

### 1) 已发布 universe：Schema / 列类型 / route / 区间不重叠

| 检查 | SH_CONNECT | SZ_CONNECT | 判定 |
| --- | --- | --- | --- |
| UniverseMembershipSchema.validate | 通过 | 通过 | **通过** |
| 必需列 | universe,symbol,effective_from,effective_to | 同左 | **通过** |
| 类型 | String/String/Date/Date | 同左 | **通过** |
| route（universe 唯一值） | SH_CONNECT | SZ_CONNECT | **通过** |
| source 列 | Schema 无 source；route 编码于 universe | 同左 | **通过**（按权威 Schema） |
| rows/symbols/coverage_start/open | 1062/919/2014-11-17/644 | 1149/1014/2016-12-05/644 | **通过** |
| 同 route+symbol 有效期严格不重叠 | 0 issue | 0 issue | **通过** |

说明：CleanUniverseMembershipStore 仅有写入 API；验证以正式 Schema 校验 parquet 为准。

### 2) 零写入 dry-run/preview，并与已发布文件逐字段相等

#### 2.1 重新 dry-run

SH 命令 exit=0：rows=1062 symbols=919 coverage_start=2014-11-17 open_intervals=644 published=false status=PASS

SZ 命令 exit=0：rows=1149 symbols=1014 coverage_start=2016-12-05 open_intervals=644 published=false status=PASS

| 冻结期望 | SH | SZ | 判定 |
| --- | --- | --- | --- |
| rows | 1062 | 1149 | **通过** |
| symbols | 919 | 1014 | **通过** |
| coverage_start | 2014-11-17 | 2016-12-05 | **通过** |
| open/current | 644 | 644 | **通过** |

#### 2.2 dry-run 零写入（本会话可证）

| 文件 | dry-run 前 bytes/mtime | dry-run 后 | sha256 |
| --- | --- | --- | --- |
| SH universe | 5703 / 1784298165 | 不变 | cf300a5daba437cebcddfa74ed4b8a497d8c829e556c548add8d1bf9aa42dbe2 |
| SZ universe | 6152 / 1784298186 | 不变 | c4501b974ce99c1ea48c3f2eaa18bd9fce0b03b9b1c0b8b27d012b5b634b9e9a |

#### 2.3 preview 与已发布逐字段相等

独立 reverse rebuild 后对四列排序 equals + 行集合相等：SH true（1062）；SZ true（1149）。**通过**

### 3) eligible_symbols_on baseline / snapshot / 基线前 fail-closed

| Route | baseline 日 | snapshot 2026-07-10 | baseline 前一日 | 判定 |
| --- | ---: | ---: | --- | --- |
| SH | 268 | 644 | 2014-11-16 → EligibilityHistoryError | **通过** |
| SZ | 417 | 644 | 2016-12-04 → EligibilityHistoryError | **通过** |

未静默返回空集或当前名单。

### 4) 变更范围隔离 / 无 temp 残留

| 证据 | 结果 | 判定 |
| --- | --- | --- |
| 两 universe 终态与执行报告一致 | SH cf300a5d… 5703；SZ c4501b97… 6152 | **通过** |
| SH/SZ clean event 与执行报告及 REAL1 一致 | db685e56… 23068；30abfb4a… 23821 | **通过** |
| snapshot/calendar mtime 严格早于 universe 发布 | 均为 true | **通过** |
| data/raw 任意文件 mtime ≥ 发布时间 | 无 | **通过**（mtime） |
| universe_membership 树 | 仅两路 data.parquet；无 tmp/partial | **通过** |

证据边界：本会话不能用 Git/发布前全库 hash 绝对证明执行窗口无任何额外写入；仅能证明授权目标终态一致、event 闭包一致、snap/cal/raw mtime 早于发布、本会话 dry-run 零写入。不影响 Schema/成员合同结论。

### 5) 执行者未使用的对抗性反例

#### ADV-A：边界/随机日成员交叉核对

区间表 eligible_symbols_on 与独立 reverse rebuild 再查询对比（seed=20260717；含 baseline/+1/snapshot/snapshot-1 + 5 随机日）：SH mismatches=0；SZ mismatches=0。
能发现：漏写/错写区间、与事件流不一致篡改、行数对但集合错。

#### ADV-B：reopen / 非 exact-adjacency 缺口语义

SH gap_gt1_pairs=143 exact_adjacency=0；SZ 135/0。抽样 00017.HK：端点日在池内、缺口日不在池内、再入日在池内（SH/SZ 均成立）；全表端点一致性扫描通过。
能发现：跨 REMOVE/ADD 错误合并、effective_to off-by-one、缺口日仍返回成员。

对抗判定：**通过**

### 6) 总判定

任一项不满足即不通过；本验证未修复任何产物。汇总 1–5 均通过 → 独立验证 **通过**（仍待主 Agent 终验）。

---

## 压缩命令/退出码

| 命令 | exit |
| --- | ---: |
| SH --dry-run reverse-audit | 0 |
| SZ --dry-run reverse-audit | 0 |
| 只读 Schema/重叠/eligible/preview 脚本 | 0 |
| ADV reopen gap 抽样脚本 | 0 |

## 后续

交主 Agent 终验；本报告不勾选路线图、不宣布 Gate/里程碑完成。
