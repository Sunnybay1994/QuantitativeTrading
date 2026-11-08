口径：对本文件「§13 标题行之前」全部 UTF-8 字节（含 §0–§11 历史与本轮 §12；**不含**本 §13 块）计算 SHA-256。
说明：文首结论行仍保留 REWORK2/3 历史表述（不改写 §0–§11 业务正文）；**本轮最新结论以 §12.5 `REVIEW_PASS` 为准**。本值于 DOC-WHITESPACE 行尾规范化后按实际标题边界重签；不再沿用「回填后正文指纹不变」旧口径。


## 14. VALIDATION5/6 独立证据复核（追加；不改写 §0–§13）

身份：M4-A2 VALIDATION5/6 全新独立证据复核 Agent（未参与运行）<br>
依据：任务书 §17、交付报告 §14–§18、既有本报告 §0–§13<br>
唯一可写：本报告；实现/测试/task/delivery/evidence **只读**<br>
约束：**未运行** Python/pytest/Ruff/mypy/cold/SQLite/网络/PAPER；**未提交**；未改 evidence 字节。

证据根（只读）：

1. `artifacts/agent_runs/m4-a2-validation5-20260825T103620Z-e53a68e4/`
2. `artifacts/agent_runs/m4-a2-validation6-20260825T104636Z-971e939a/`
3. `artifacts/agent_runs/m4-a2-validation6-final-scope-20260825T104933Z-4d19245b/`
4. `artifacts/agent_runs/m4-a2-validation6-residue-close-20260825T105138Z-e4f3c46a/`

### 14.1 逐根 exit / stdout / stderr / summary 与声称 SHA

| 根 | summary 终态 | 关键阶段 | exit 文件 | stdout 语义 | stderr | 交付声称 SHA | 实测 SHA-256 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V5 | `VALIDATION5_STOP STAGE_FAILED:4:mypy:1`；顺序 identity→pytest→ruff→mypy | pytest-focused | `0` | `239 passed, 56 warnings in 13.10s` | 0 B | `A80E40E9…3DC440` | `A80E40E9647E566D82A31A15F9F6C336ED258A576937B7987C4BB6E36F3DC440` | 一致 |
| V5 | 同上 | ruff | `0` | `All checks passed!` | 0 B | （未单独给 SHA） | `82B3E6A6C090A57601D22943BD23FCA9218D1031DBE5A7B754092F9A156B4F18` | PASS 语义一致 |
| V5 | 同上 | mypy | `1` | `service.py:453` `attr-defined`；`Found 1 error in 1 file (checked 8 source files)` | 0 B | `EC5AF65F…777D2C` | `EC5AF65F17AA4753412B87646447CDCB7AC84A0B83C0F7D37466E4179E777D2C` | 旧失败证据保留且 SHA 一致 |
| V6 | `VALIDATION6_STOP STAGE_FAILED:5:final-scope:1`；顺序 identity→pytest→mypy→cold→final-scope | pytest-directed | `0` | `5 passed in 3.10s` | 0 B | `F2D600D1…18D556` | `F2D600D1769186836F5E491592B0CE5663D1DB104FD9DC82E5CD3C300A18D556` | 一致 |
| V6 | 同上 | mypy | `0` | `Success: no issues found in 8 source files` | 0 B | `7AEFCACC…C6E96F6` | `7AEFCACC6D445354A115CF76FCDEA696165BE7AD8CF9B86A60EA98727C6E96F6` | 一致 |
| V6 | 同上 | cold-import | `0` | 精确 8 个 production 路径 | 0 B | （未单独给 SHA） | `B9478598998DA627B04E934384D8EB86C801C2979265BB61B54A5E3C4EB9897C` | cold8 语义一致 |
| V6 | 同上 | final-scope | `1` | STATUS 列出工作树变更 | 非空：`CACHE_RESIDUE:.mypy_cache` | — | stderr `00D423A75292A0A972310B353F7F05E28CFE61A9770B10F1CA4C5B8091CF4EA8` | **carrier cache STOP**，非产品红灯 |
| final-scope | `…STOP STAGE_FAILED:4:temp-cache-residue`；exact18→cached→diff→temp | exact18 / cached0 / diff-check | 均 `0` | `EXACT18_SCOPE_PASS` / `CACHED_ZERO_PASS` / `DIFF_CHECK_PASS` | 0 B | — | exact18 stdout `147DBBD9…C83044` | 产品 scope 三阶段 PASS |
| final-scope | 同上 | temp-cache-residue | `1` | `.ruff_cache exists=True`；其余三 cache/` .tmp` False | 非空：`RESIDUE:.ruff_cache` | — | stderr `81556720…544F741` | **ruff cache STOP** |
| residue | `VALIDATION6_RESIDUE_CLOSE_PASS` | exact-cache-absence | `0` | 四路径均 `exists=False` + `EXACT_CACHE_ABSENCE_PASS` | 0 B | `958C3C28…AAB174` | `958C3C288A61106C188697DD37910C94B369BDDEDF23BD34AB1A35586AAAB174` | 一致 |
| residue | 同上 | process-affinity | `0` | 无 `0xF00`；`id=7692 name=python affinity=0x3 priority=BelowNormal` + `PROCESS_AFFINITY_PASS` | 0 B | `E174A05C…BDC12BD` | `E174A05C8BF083FB981F7904B47C30FE93FF4CD1E9F17B774E1B05239BDC12BD` | 一致 |

### 14.2 Cache STOP 诚实性（不掩盖产品失败）

1. V6 产品阶段（定向 5 / mypy8 / cold8）在 `05-final-scope` **之前**全部 exit=0；STOP 仅因 `.mypy_cache` carrier residue。
2. final-scope-1 产品阶段（exact18 / cached0 / diff-check）全部 exit=0；STOP 仅因 `.ruff_cache`。
3. 两根 STOP 证据仍完整保留（no-clobber）；residue-close 仅证明四 cache 缺席 + process 边界，**未改写**既有 STOP 根。
4. 交付 §16/§17 标明 `REGENERABLE_*_CACHE_RESIDUE` 且首失败未自行重跑产品阶段；§18 合并口径不把 V5 mypy 旧失败改写成 PASS。
5. 结论：两次 cache STOP 为 **carrier residue**，精确清理后闭合；**不掩盖**产品/静态失败。

### 14.3 P2 / P3 / review E / H / I 诚实性

| 边界 | 本轮证据复核结论 |
| --- | --- |
| 既有 [P2] capability `__new__` 字段克隆 | 交付 §14/§18 与本报告 §3/§8/§10/§12 **仍保留**；未宣称消除 |
| 既有 [P3] equality 忽略 secret/proof | 同上保留 |
| review E（`RecoveryResult.__new__` allow-set） | 同上保留 |
| review H / I（`.code` 事后分叉；非 str 构造注解-only） | §12.2–§12.3 P3 诚实边界仍在；证据复核未改写、未降级为“已修复” |

无证据表明 VALIDATION5/6 运行或 residue close 被用来洗白上述进程内 authority 边界。

### 14.4 执行者未使用的证据对抗检查（本轮新增）

**对抗 J：exit=0 ↔ stdout 语义耦合；0-byte stderr；summary 顺序；旧失败未覆盖；exact18 含审查报告**

1. **exit↔stdout：** 所有 exit=`0` 阶段 stdout 含明确 PASS/`passed`/`Success`/`All checks passed`；exit=`1` 阶段 stdout/stderr 含失败语义（mypy `Found 1 error` 或 `CACHE_RESIDUE`/`RESIDUE`）。未发现 exit=0 却带失败关键字。
2. **0-byte stderr：** 全部 PASS 阶段 stderr 均为空文件 SHA `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`；两 cache FAIL 阶段 stderr 非空且与 throw 文案一致。附带观察：V5 mypy exit=1 时 stderr 仍 0 B、错误在 stdout——与 mypy 行为及交付引用 stdout SHA 一致，**不**构成 exit/stdout 矛盾。
3. **summary 顺序：** 四根 `stage-summary.log` 阶段编号与文件前缀、首失败停机一致；V5 无 cold/final-scope 产物；V6 STOP 后未冒充整包 Gate。
4. **旧失败未覆盖：** V5 `04-mypy.*` 与 SHA `EC5AF65F…` 仍在独立根内可读；与 V6 mypy PASS 根并存，未被 residue-close 覆盖。
5. **exact18 含报告：** `01-exact18-scope.stdout.log` 精确 18 条路径（13×` M ` + 5×`??`），**包含** `docs/framework/reviews/M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`，并以 `EXACT18_SCOPE_PASS` 收尾。

### 14.5 逐文件 SHA 抽查（补充）

| 文件 | SHA-256 |
| --- | --- |
| V5 `stage-summary.log` | `850FFC0651CF36962000F45CCF72D9EF9D77B27D4F7417FBE01E9DB83F8C09FD` |
| V6 `stage-summary.log` | `0CB4069B952020465027AE5FBEED7AE23598649291EF7840294FF95CA9D478FB` |
| final-scope `stage-summary.log` | `9142419EED2E0A4623AC5245F25884DC65899B57128C0260E8052691D29A316E` |
| residue `stage-summary.log` | `8FD62CC6C1BFC9A0F79927174D71A3773B43648DDA4C919D700AE090CB50D1D3` |
| V6 `04-cold-import.stdout.log` | `B9478598998DA627B04E934384D8EB86C801C2979265BB61B54A5E3C4EB9897C` |
| final-scope `01-exact18-scope.stdout.log` | `147DBBD99C1E0EC9BC6B8355E28DC3DD5E0B080B8886EABF8EFB009702C83044` |
| exit=`0` 哨兵（`0\r\n`） | `13BF7B3039C63BF5A50491FA3CFD8EB4E699D1BA1436315AEF9CBE5711530354` |
| exit=`1` 哨兵（`1\r\n`） | `F1B2F662800122BED0FF255693DF89C4487FBDCF453D3524A42D4EC20C3D9C04` |

### 14.6 未运行边界（本复核强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行**（本 Agent） |
| SQLite / 网络 / PAPER / broker | **未运行** |
| Git commit / stage / merge | **未执行** |
| 改写 evidence / 实现 / 测试 / 任务 / 交付 | **未执行** |
| SAFE_COMMIT / Linux Gate / UA-M4-006/007 | **不声称** |
| 本结论范围 | **仅持久证据复核**；不等于重新执行验证 |

### 14.7 发现分级与结论

### 无 P0 / P1

### 无证据矛盾

**EVIDENCE_REVIEW_PASS**

合并口径与交付 §18 一致且可核：V5 focused 239 + Ruff PASS、mypy 旧失败证据保留；V6 定向 5 + mypy8 + cold8 PASS 后仅 mypy cache STOP；final-scope exact18/cached0/diff-check PASS 后仅 ruff cache STOP；residue 四 cache absent + writer PID7692/`0x3`、无 `0xF00`。两次 cache STOP 为 carrier residue，精确清理后闭合，不掩盖产品失败；P2/P3/review E/H/I 仍诚实保留。

报告路径：`docs/framework/reviews/M4_P8_A2_FormalDurableApprovalE2E独立初验报告.md`

## 15. VALIDATION5/6 证据复核报告 SHA256（前置说明；DOC-WHITESPACE 规范化后重签）

`5a4be0560546d8ddf37d7893bc12e3d1cff1f2817b53029d6d794b130e97b475`

口径：对本文件「§15 标题行之前」全部 UTF-8 字节（含 §0–§13 历史与本轮 §14；**不含**本 §15 块）计算 SHA-256。
说明：文首结论行仍保留 REWORK2/3 历史表述（不改写 §0–§13 业务正文）；**本轮最新结论以 §14.7 `EVIDENCE_REVIEW_PASS` 为准**。本值于 DOC-WHITESPACE 行尾规范化后按实际标题边界重签；不再沿用「回填后正文指纹不变」旧口径。

## 16. DOC-WHITESPACE 独立复核（追加；不改写 §0–§15 业务结论）

身份：M4-A2 DOC-WHITESPACE 全新独立 reviewer（STATIC_ONLY）
唯一可写：本报告；taskbook / delivery / 实现 / 测试 / evidence **只读**
约束：未运行 Python / pytest / Ruff / mypy / cold / SQLite / 网络 / PAPER；未 commit / stage。

### 16.1 三文档行尾空白

| 文档 | 行尾空白行数 | 行尾空白字符数 |
| --- | --- | --- |
| 任务书 `docs/framework/tasks/M4_P8_A2_FormalDurableApprovalE2E任务书.md` | 0 | 0 |
| 交付报告 `docs/framework/deliveries/M4_P8_A2_FormalDurableApprovalE2E交付报告.md` | 0 | 0 |
| 本审查报告（规范化后） | 0 | 0 |

### 16.2 格式语义与写集

- taskbook / delivery：仅行尾双空格 → 显式 `<br>`（或等价去尾随空白）的**格式语义等价**规范化；业务措辞 / 合同 / 状态 / 证据 SHA / 路径未改（以交付 §16 记录为准；本轮只读复核）。
- 本报告：强制换行元数据栈改为显式 `<br>`，其余段落/列表仅去除尾随空白；**不改** P2/P3 / review E/H/I / `EVIDENCE_REVIEW_PASS` / `REVIEW_PASS` 业务结论。
- 生产代码与测试：**不在**本轮写集。

### 16.3 `git diff --check` 预期与 untracked 说明

- 普通 `git diff --check`（对已跟踪变更）**预期 PASS**：工作树中上述三文档当前均为 **untracked（`??`）**，普通 `git diff` / `git diff --check` **不会**把未跟踪文件纳入 diff，因此先前 taskbook/delivery 的行尾双空格问题**不会**被普通 diff-check 覆盖或报出。
- 本轮静态逐行字节审计确认三路径行尾空白均为 0；不以“diff-check 曾绿”代替未跟踪文件的行尾审计。

### 16.4 业务结论复核（未改）

| 项 | 状态 |
| --- | --- |
| 既有 [P2] / [P3] | 保留（§3 / §8 / §10 / §12） |
| review E / H / I | 保留 |
| `EVIDENCE_REVIEW_PASS`（§14.7） | 未改 |
| 各轮 `REVIEW_PASS` | 未改 |

**DOC_REVIEW_PASS**（仅 DOC-WHITESPACE 文档卫生与重签；不等于运行验证或 Gate）

## 17. DOC-WHITESPACE 复核报告 SHA256（前置说明）

`6a342a044c7aa6ea8bd9a977c9f156cbd74fb627cf96552bc37acdaa55dd2f7e`

口径：对本文件「§17 标题行之前」全部 UTF-8 字节（含 §0–§16；**不含**本 §17 块）计算 SHA-256。本值于 DOC-WHITESPACE 规范化与 §7/§9/§11/§13/§15 重签完成后按实际标题边界计算。
整文件 SHA-256（本行之前完整文件 UTF-8 字节）：`755b92005c7a13dbecd066cd9df697ac2ec2ab863886492eb25756e5afd90d32`
