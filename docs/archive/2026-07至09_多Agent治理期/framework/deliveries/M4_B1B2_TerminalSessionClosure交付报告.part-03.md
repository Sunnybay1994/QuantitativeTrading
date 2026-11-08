| 轮次 | evidence root | 阶段结果 | 关键 SHA / 备注 |
|---|---|---|---|
| **V1** | `artifacts/agent_runs/m4-b1b2-validation1-20260826T062412Z/` | identity **PASS**；focused **FAIL** `555 passed / 4 failed / 7 skipped`；Ruff/mypy/cold/scope **UNRUN** | summary_sha=`8503F5662B32B885135AE7C16BF27B14C1AA3346DCE341BF95B76FEDBC20B7B0`；focused stdout=`29728EC681014FF8C1B1C573A9690AB012FAE0FAFF70108872C96FE15224C845`；`VALIDATION_STOP=STAGE_FAILED:02-focused:1` |
| **V2** | `artifacts/agent_runs/m4-b1b2-validation2-20260826T064500Z/` | identity **PASS**；focused **PASS 559/7**；Ruff **FAIL** 6×F401/F811；mypy/cold/scope **UNRUN** | summary_sha=`452F153BBABCEA9BB33E448D73A263474C59AD88784245AA46876B5586F909DB`；focused stdout=`EF6A236EBA6DD969155BDBA2528D13904D2CD0AF102C0B8B0D6F23BDAB959E0E`；ruff stdout=`366B9997ABEE83617B48CECD8CF2457C7DEC79018314193E9B6BC6BED6F88064`；`VALIDATION_STOP=STAGE_FAILED:03-ruff:1` |
| **V3** postfix | `artifacts/agent_runs/m4-b1b2-postfix-validation3-20260826T071119Z/` | identity **PASS**；Ruff exact30 **PASS**；mypy **FAIL** 14×attr-defined；cold/scope **UNRUN**；focused 未重跑（沿用 V2） | summary_sha=`6EDCE34C52DEBAAA4CCF180DF1DB8F46637EFE281F8C548009649544AD414B67`；ruff=`AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF`；mypy=`50441960AFDAED980CA6D27209BFC090C4EFFA28D3BF6B80C410FF2C8F5F5299`；`VALIDATION_STOP=STAGE_FAILED:04-mypy:1` |
| **V4** postfix | `artifacts/agent_runs/m4-b1b2-postfix-validation4-20260826T072258Z/` | identity **PASS**；Ruff（`paper_formal_service.py`）**PASS**；mypy **PASS**；cold **PASS**；内嵌 06-scope **FAIL** `SCOPE_EXTRA`（docs 三路径）；focused **未重跑** | summary_sha=`E32F81546727997FAB3ECB3C1371AB3FAED6C88717B1A3FE5B05EBF5E4C78B44`；identity stdout=`87CDF9814A6CD3996FF7242BB6EC2EE9819512DC88402B1567BFE336E392473E`；ruff=`AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF`；mypy=`6F0C27F692C09599FBC86EA808B561C162AB771E55F74A9E4B924040F2A63061`；cold=`756443DBED6C96AB83C3BB51809C2267BF75979484644CD566F1A4B5CB000B65`；06-scope stderr=`DCFC2A992AA8EA87F1196547F6A3D850A70E9076E72F2F0297CBA9F5C12524E4`（无 06-scope.stdout；runner 在缺文件处 STOP） |

说明：V4 **工程四段**（identity/Ruff/mypy/cold）绿；单轮内嵌 scope **未**绿，由独立 scope-close5 组合闭合，不把 V4 叙述成“含 scope 的单轮全绿”。

### 20.3 scope-close1–5（首失败保留；5 PASS）

| # | evidence root | 结论 | 首失败 / 通过要点 | 关键 SHA |
|---|---|---|---|---|
| **1** | `artifacts/agent_runs/m4-b1b2-validation4-raw-bytes-scope-20260825T235204Z/` | **FAIL** | `GIT_STATUS_RECORD_INVALID`（NUL 分隔 status carrier 解析） | 01-scope.stderr=`2AA21EDA4D515EC445CFD93A775D91D9628143B216E5F6DCC92F796451E53AFB`；git-status.raw=`48132F7E31D80D8448363563D889E8C346D19E8DF366B019D4405BFAE230CD0E` |
| **2** | （无独立目录名 `scope-close2`）同位：V4 内嵌 `06-scope` 见上表 | **FAIL** | `SCOPE_EXTRA`：task/delivery/review 三 docs 路径（编码/白名单 carrier） | stderr=`DCFC2A992AA8EA87F1196547F6A3D850A70E9076E72F2F0297CBA9F5C12524E4` |
| **3** | `artifacts/agent_runs/m4-b1b2-validation4-scope-close3-20260825T235504Z/` | **FAIL** | 再次 `GIT_STATUS_RECORD_INVALID` | 01-scope.stderr=`1BCC8BC2BC758402585AC4C8247D7EF6F89F123FAD43B2A04101E2DB1E3C384E` |
| **4** | `artifacts/agent_runs/m4-b1b2-validation4-scope-close4-20260825T235812Z/` | **FAIL** | `ConvertFrom-NulPayload` 对空 `cached` Bytes 无 `AllowEmptyCollection` | 01-scope.stderr=`007A9FA6E3E79E577E60D658C337DDFE0059BEC9B7F663355B34C85004B1819A` |
| **5** | `artifacts/agent_runs/m4-b1b2-validation4-scope-close5-20260826T000341Z/` | **PASS** | `RAW_BYTES_SCOPE_PASS`；`ACTUAL_COUNT=19`；`ALLOWED_COUNT=33`；`CACHED_COUNT=0`；`DIFF_CHECK=PASS`；`TEMP_CACHE=ABSENT`；`F00_RESIDUE=0`；`WRITER_PID=7692`；`WRITER_PRIORITY=BelowNormal`；`WRITER_AFFINITY=0x3` | 01-scope.stdout=`DE6BE7EBB4351DBDCDBFBC9476FA742B659FCCF080B2DAC5B761ABEA85C4F27F`；exit=`5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9`；git-status.raw=`48132F7E31D80D8448363563D889E8C346D19E8DF366B019D4405BFAE230CD0E`；git-cached.raw / git-diff-check.raw = empty SHA `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` |

附加保留（不推翻 sc5）：`artifacts/agent_runs/m4-b1b2-validation4-scope-close-20260826T074843Z/` 再次 `SCOPE_EXTRA`（docs 路径）；stderr=`1E1404DF3B9963B7B4E58DEFA6BBFFFDCBA1C899AA8C31BEB1D27EE1330E50B3`。

#### scope-close5 actual19 清单（⊆ exact33）

```
docs/framework/deliveries/M4_B1B2_TerminalSessionClosure交付报告.md
docs/framework/reviews/M4_B1B2_TerminalSessionClosure独立初验报告.md
docs/framework/tasks/M4_B1B2_TerminalSessionClosure任务书.md
src/quant/execution/migrations/__init__.py
src/quant/execution/migrations/v010_terminal_successor.py
src/quant/execution/paper_broker_store.py
src/quant/execution/paper_formal_broker_snapshot.py
src/quant/execution/paper_formal_execution_store.py
src/quant/execution/paper_formal_service.py
src/quant/execution/session_barrier.py
src/quant/execution/soak.py
src/quant/execution/soak_runtime.py
src/quant/execution/store.py
tests/unit/test_execution_soak.py
tests/unit/test_execution_store.py
tests/unit/test_paper_formal_broker_snapshot.py
tests/unit/test_paper_formal_execution_store.py
tests/unit/test_paper_soak_runtime.py
tests/unit/test_session_barrier.py
```

### 20.4 本闭合会话边界

- 可写：delivery（本 §20）+ 任务书 §15.1 索引；**未改** production/tests/review 业务字节
- **零** Python / pytest / Ruff / mypy / cold / SQLite / 脚本 / PAPER / soak / network / stage / commit
- cached0 / `git diff --check` PASS（本机只读核对，与 sc5 一致意图）
- 下一步：原独立 reviewer 唯一 review 写 `EVIDENCE_REVIEW_PASS` 或 FAIL；**仅 PASS 后**申请安全提交

### 20.5 交接

- 状态：`B1B2_WINDOWS_ENGINEERING_VALIDATED / STATIC_ONLY` → 对外回报 `DELIVERY_READY`
- Gate 边界：`UA-M4-006` 继续 **OPEN**；无真实 PAPER/soak/Linux 关闭声明
- 本 adopter 退出证据写入；不 stage、不 commit
