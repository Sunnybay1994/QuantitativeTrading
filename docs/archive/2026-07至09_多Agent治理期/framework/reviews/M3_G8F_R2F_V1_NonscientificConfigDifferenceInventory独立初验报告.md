# M3-G8F-R2F-V1 Nonscientific Config Difference Inventory 独立初验报告

日期：2026-08-28<br>
结论：`REVIEW_PASS / CONTRACT_STOP / USER_CHOICE_REQUIRED`

## 1. 审查身份与范围

- task id：`M3-G8F-R2F-V1-NONSCIENTIFIC-CONFIG-DIFFERENCE-INVENTORY`
- exact base / HEAD：`2c2fe86ebd3eba1a77f3728414404dc8e9358ac8`
- taskbook SHA-256：`a58bdc77aa258243a6fd3399bbf8be6d10df3d03c4f8106cbbea50d7551c0eba`
- delivery SHA-256：`bbfcea346d1fb953c225905185b9c37b374556b91a087515320252ddb1e42020`
- 审查方式：tracked-only `STATIC_ONLY / CPU NONE`；未运行 Python、pytest、Ruff、mypy 或 Qlib。
- 唯一写入为本报告；未读取 example 具体值、LOCKED、ignored/local 或真实 data，未创建 config、request、root 或 evidence。

## 2. 148/148 field-shape 与 projection 闭包

我从 `config.py::_field_specs` 的显式 `add` 与固定循环展开重建 shape 边界，得到连续分组 `34 + 39 + 42 + 33 = 148`。交付矩阵实际包含编号1至148的148行，无断号、重号或 loop-expanded shape 遗漏。源码还以 `len(specs) != 148` fail closed，tracked测试对实例assignment shape与 `_FIELD_SPECS` 做exact set equality；本轮只将它们作静态合同证据，未执行测试。

独立重算 selector 计数与交付一致：

| 闭包 | shape数 | 静态根据 |
|---|---:|---|
| raw / full | 148 | raw为exact TOML bytes SHA；full payload为全部normalized document |
| scientific | 88 | meta envelope 1 + data 13 + Qlib version 1 + features 7 + labels 6 + walk-forward 7 + model 20 + portfolio 6 + backtest 15 + evaluation 1 + costs 11 |
| g1 | 30 | config-version envelope 1 + G1 identity/coverage/reconciliation 29 |
| snapshot | 14 | config-version 1 + data 11 + warmup/tail 2 |
| provider / provider-validation | 5 / 5 | config-version分别与4个provider或validation shape闭合 |
| label-reconciliation / acceptance | 5 / 9 | config-version分别与4个label或8个acceptance shape闭合 |
| tracking-target | 2 | canonical URI + experiment name |
| 无derived selector | 13 | purpose/enabled 2 + Qlib supply-chain policy 4 + G1 rate/retry 3 + artifact root/log flags 4 |

`_trusted_config_sha256` 证明full与derived selector共用同一canonical envelope，`meta.config_version`只作为envelope namespace而不在payload重复。`_project` 只纳入field spec显式指定的selector，因此交付的raw/full/scientific划分与源码一致。

## 3. direct consumer join 核验

- `successor_runtime._validate_request` 对每个config fresh read/load，并强制raw identities=2、full identities=2、scientific identities=1；因此fold/lane不能通过scientific字段区分。
- `successor_bridge` 从request item分别绑定fold、config path/raw/full SHA，同时要求两config的Qlib tool spec exact一致、`project_stage_root` 收敛到同一controlled PROJECT root。
- G1、snapshot、provider、provider-validation、label-reconciliation、acceptance 各selector均有对应artifact/manifest/quality consumer；其中tolerance/coverage字段直接决定fail/pass，不能作为为了区分hash的lane参数。
- `canonical_tracking_target_key`、tracking marker/request/verify path 共同绑定URI、experiment与target key；不同target会拆分tracking closure，不能替代request-side fold identity。
- `acceptance_upstream` 要求 `meta.enabled is True`；`acceptance_work` 实际消费reproducibility与coverage/IC thresholds。这些证据支持对24个技术可变non-scientific字段中21个的拒绝结论。

## 4. 独立对抗审查

### R1：条件候选 `request_rate_per_minute`

该字段在 `_field_specs` 中无derived selector，改变它只改normalized full/raw，不改scientific或g1 selector。但它不是无意义填充：`build_g1_static_plan`将其绑入`G1StaticPlanV1`，`_static_plan_sha256`将其纳入canonical payload，`g1_workflow` 再将它传给Tushare/CNInfo执行器的rate limiter。

反例结论：两个任意不同数值虽可以满足runtime的full distinct，但仍不可准入。future owner必须同时冻结两个exact值、lane mapping、真实API quota/调度根据，并提供对应G1 release的acquisition/static-plan policy证据。尤其是G1 manifest的公开字段未直接持久化rate数值本身，不能仅由release manifest的存在倒推当时quota。没有这组外部可验证policy闭包时，C1必须拒绝并转`NO_JUSTIFIED_DIFFERENCE / ARCHITECTURE_REVIEW_CANDIDATE`。C2/C3同理，分别还需失败预算与退避策略证据。

### R2：技术可变但业务不正当的 `meta.purpose`

`meta.purpose` 是非fixed且无selector的字段，所以改它确实能改full/raw而不改scientific。但源码中没有将其作为fold/lane执行信息的direct consumer，而fold已由request item及其config path/raw/full SHA显式绑定。用purpose文本制造两个full hash是无业务不变量支撑的identity padding，必须拒绝。

### R3：注释/空白只改raw

`load_m3_config` 对exact raw bytes先取SHA，而full hash对TOML parse、strict validate与normalize后的document取canonical JSON SHA。因此仅作语义保持的TOML注释/排版变化时，raw会改变而full与derived identities不变；一旦排版变化改了字符串值或parse tree，则不属于此反例。runtime的full identity set因而仍为1，必然fail closed。tracked test也有同一静态合同，但本轮未运行它。

## 5. 结论与剩余边界

`REVIEW_PASS`。交付的148/148矩阵、selector计数、direct consumer joins、24/24技术可变字段分类与三个条件候选结论与tracked source一致，未发现P0/P1。

此PASS只表示静态盘点可作为future owner决策输入，不选择任何字段或数值。当前终态仍为：

`NONSCIENTIFIC_DIFFERENCE_INVENTORY_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`

若owner无法提供两个真实G1 lane的配额/重试差异与对应release policy证据，三个候选必须全部拒绝并进入runtime distinct-full合同的架构重审。本包未创建formal config/request/root，未关闭A13/A14/A16/A19，未推进actual successor、Qlib或M3 Gate。

## 6. 静态核验记录

- HEAD：`2c2fe86ebd3eba1a77f3728414404dc8e9358ac8`
- 交付矩阵：148行，编号1至148连续。
- task/delivery/source anchor SHA与交付声明一致；源码anchors均为tracked HEAD blobs。
- 运行验证：`UNRUN (STATIC_ONLY)`。
- 审查写入后应保持actual exact3、cached=0，并由经理复核ordinary `git diff --check`与文档字节卫生。
