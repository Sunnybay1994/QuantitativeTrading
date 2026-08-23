# M3 G1-P4A：主验一次返工任务单

日期：2026-07-14  
状态：P1-1 返工、全新独立复验及主 Agent 二次终验均已通过；仅关闭 P4A 子包  
原任务：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)  
实现交付：[`M3_G1_P4A候选与主审计交付报告.md`](M3_G1_P4A候选与主审计交付报告.md)  
初验报告：[`M3_G1_P4A候选与主审计独立初验报告.md`](M3_G1_P4A候选与主审计独立初验报告.md)

## 1. 结论与范围

独立初验通过不等于主验通过。主验发现 `G1Candidate` 构造身份未自证，定为 **P1-1**。只修本项及直接测试，
不开始 P4B/P4C，不修改 P2/P3、connector、RawStore、配置或路线图。

允许修改：

- `src/quant/data/m3_g1_candidate.py`；
- `tests/unit/test_m3_g1_candidate.py`；
- 本轮返工交付报告。

如无需新增公开符号，不修改包根导出或 Schema。不得联网、读 token、访问 `_old/` 或写数据/release。

## 2. 现象—根因—规则

### 现象

`G1Candidate.__post_init__` 当前只重建 build spec/plan、检查日期/receipt 顺序，并对
`price_limit_required_keys_sha256`、`primary_candidate_key` 和 `table_content_digests` 做形状/64 hex 检查。
以下对象当前可构造成功：

1. `dataclasses.replace(candidate, primary_candidate_key="f" * 64)`；
2. 替换任一内含 frame 的业务值但保留原 `table_content_digests`/primary key；
3. 只替换 required-keys digest，或把 required digest 与 primary key 同步成另一套内部自洽值，但对象内
   calendar/instrument/eligible/suspension 推导出的 required keys 未改变。

调用 `audit_g1_candidate` 或 `verify_g1_candidate(inputs=...)` 后才会发现，不改变构造已接受伪造值对象的事实。

### 根因

实现把三层职责混在一起：

- constructor identity closure：对象内字段与派生身份必须自洽；
- audit：收集可安全检查的跨表质量问题；
- verify with original inputs：从冻结输入重执行，证明来源闭包。

后两层存在不能替代第一层。原独立初验验证了 audit/verify 拒绝，却没有直接对构造器做 hash/frame 漂移攻击。

### 应遵循规则

任务书 §3 已补充明确：`G1Candidate.__post_init__` 必须从对象内证据重算 14 表 digest、required-keys digest 和
primary key；仅检查合法 hex 不构成自证。Schema/coercion 如产生规范 frame，必须写回对象后再计算 digest，避免
“按规范 frame 算 hash、却暴露原 frame”的旧缺陷复发。

## 3. 冻结最小实现

1. 抽取一个无 IO、无网络的内部 candidate identity verifier，供 `G1Candidate.__post_init__` 使用；不得调用
   `audit_g1_candidate` 生成 issue report，也不得要求原始 `G1BuildInputs`。
2. 严格建立 14 个字段到 `_TABLE_NAMES` 的唯一映射；逐表按现行 Schema 验证，`eligible_keys` 按其冻结精确合同
   验证；把规范化/coerced frame 写回 dataclass。
3. 用 P2 已验收 `clean_table_content_sha256` 对规范 frame 重算 14 个 content digest；要求传入 tuple 与按表名字典序
   的重算结果精确相等。
4. 从对象内 `calendars/instruments/eligible_keys/suspensions`、四日期/现行持仓延续规则重建 required
   price-limit keys，重算 `price_limit_required_keys` digest，并与字段精确相等。不得只信字段或从 price-limit
   clean 行倒推 required domain。
5. 用规范 build spec、request plan `plan_sha256`、四日期、排序 receipt projections、重算后的 14 digest 与
   required digest 调现行唯一 `_primary_candidate_key`，与字段精确相等。
6. frame/表 digest/required digest/primary key 任一漂移均稳定
   `G1_CANDIDATE_IDENTITY_MISMATCH`；非法类型/Schema 使用现行稳定边界，不泄露值、路径或 token，异常
   `__cause__ is None`。
7. 保持 `verify_g1_candidate(inputs=...)` 的原输入重执行来源闭包和 `audit_g1_candidate` 的多 issue 收集语义；
   不因 constructor fail-fast 删除或弱化二者。

若 required-keys helper 当前只在 build/audit 内有重复逻辑，应做最小内部复用，不新增公开 API、不重构无关路径。

## 4. 最小复现与新增测试

必须直接测试构造器，不得只断言 audit/verify：

1. `replace(valid, primary_candidate_key="f"*64)` 构造失败；
2. 每张 14 表至少做逐表参数化：改一个业务值或增删/重复一行，保留旧 digests/key，构造失败；
3. 只改某个 table digest 并同步 primary key，frame 不变，构造失败；
4. 只改 required digest；以及同步 required digest+primary key但对象内 required domain 不变，构造失败；
5. 合法 frame 使用可安全 coercion dtype 时，若 Schema 接受，构造后对象暴露规范 frame且重算 digest一致；有损或
   不可 coercion 类型稳定失败；
6. 四种攻击同时覆盖正常 constructor 与 `dataclasses.replace`；失败码、`str/repr/cause/traceback` 脱敏；
7. 合法 candidate 的 build→constructor→audit→verify 原路径不回归，wholesale 自洽来源替换仍由带原 inputs 的
   verify 拒绝。

## 5. 通过条件与报告

只在 WSL Miniforge `base` 运行定向 P4A、全量 pytest、Ruff、mypy。生成
`docs/M3_G1_P4A主验一次返工交付报告.md`，逐项映射本任务单，状态只可写“返工已交，待独立复验”。

返工后必须使用未参与本轮实现的全新 `cursor-grok-4.5-high` 会话，只读生成
`docs/M3_G1_P4A主验一次返工独立复验报告.md`；复验须直接攻击构造器并补实现者未用变体。复验通过后才可再次
交主 Agent，期间不得开始 P4B/P4C 或声明 P4A/B4/G1/Gate 通过。
