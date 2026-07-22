# M3 G1-P2 B3：独立初验 P1-1 一次返工任务单

日期：2026-07-14  
状态：返工与独立复验已通过，且已通过主 Agent 最终验收；见 [`M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md`](M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md)  
原任务：[`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](M3_G1_P2_B3PIT成员状态外部闭环任务单.md)  
不通过证据：[`M3_G1_P2_B3PIT成员状态独立初验报告.md`](M3_G1_P2_B3PIT成员状态独立初验报告.md)

## 1. 裁决

主 Agent 复核源码后确认独立初验的 **P1-1 成立**。`ObservedMembershipResult.__post_init__` 对三张输入表
调用 validator，并用 validator 返回的 coerced frame 计算摘要，却继续暴露调用方传入的原 frame。成功对象
因此可能出现“公开表仍是 Utf8 日期、摘要描述的是 Date 表”。消费侧 verifier 能拒绝不能弥补构造边界已经
产生自相矛盾对象；这是 Schema-first 与 clean identity 闭包缺口，不得降为 P2。

## 2. 现象—根因—规则—最小复现

### 现象

把合法 `observations.observation_date` 转为 Utf8，用 `IndexConstituentObservationSchema.validate` 返回的 Date
表计算摘要，再以“原 Utf8 表 + Date 表摘要”构造 `ObservedMembershipResult`：当前构造成功，但
`clean_table_content_sha256(frame=result.observations) != result.observations_sha256`。

### 根因

`__post_init__` 的局部变量 `observations/membership/eligible` 是规范化结果，但没有通过
`object.__setattr__` 写回 frozen dataclass；摘要与公开属性来自不同对象。

### 应遵循规则

1. `Config.coerce=True` 的 Schema/validator 是消费边界，后续只能使用其返回 frame。
2. 成功构造的值对象必须自证：每个公开 frame 的 clean digest 与相应公开 digest 字段立即相等。
3. 三张表必须一致处理，不能只修已被反例命中的 observations。
4. 先完成三张表验证，再写回三张规范 frame，再从写回对象计算并比较 digest；不得手工 cast 或复制 Schema。
5. 不可 coercion 输入继续以既有稳定错误码 fail-closed，异常 cause/路径/token 不泄露。

### 最小复现与通过条件

原初验报告 §5 的最小复现必须关闭。修复后允许两种设计中的唯一一种：当前任务冻结为**成功构造并规范化
写回**，即公开 `observation_date` 为 `pl.Date`，且公开表重算摘要与字段相等。不要改为拒绝所有本可由生产
Schema 合法 coercion 的输入，否则会与 Schema SSOT 分叉。

## 3. 最小实现范围

允许修改：

```text
src/quant/data/index_membership.py
tests/unit/test_index_membership.py
docs/M3_G1_P2_B3PIT成员状态初验一次返工交付报告.md
```

禁止修改 `m3_identity.py`、领域 Schema、包根导出、原交付/初验报告、配置、任务书之外生产模块、路线图和
Gate。若现有公共签名或 Schema 必须改变才能修复，停止并提交证据，不得自行扩大范围。

## 4. 实现 Agent 必测

1. observations：`observation_date=Utf8` + 基于 validator 返回 Date 表的正确摘要，构造成功后公开 dtype 为
   Date，且公开表重算摘要相等；
2. membership：`effective_from/effective_to=Utf8` 的可 coercion 变体同样写回规范 frame并自洽；
3. eligible keys：`as_of=Utf8` 的可 coercion 变体同样写回规范 frame并自洽；
4. 三张表同时使用可 coercion dtype，三组公开摘要全部等于对公开 frame 的重算值；
5. List/Struct 等不可 coercion dtype 仍用既有 result/table 错误语义拒绝，`__cause__ is None`；
6. 正常 `build_observed_membership`、严格 verifier、构造后 drift、自洽整体错移反例不退化；
7. 定向、全量、Ruff、mypy 全部通过。

返工报告必须写明实际模型 `cursor-grok-4.5-high`、修改文件、三表 write-back 顺序、测试数量与命令结果；只
声明“待独立复验”，不得宣称 P2/G1/Gate 通过。

## 5. 独立复验

返工后使用未参与实现的全新 `cursor-grok-4.5-high` 会话，只允许写：

```text
docs/M3_G1_P2_B3PIT成员状态初验一次返工独立复验报告.md
```

复验不得只重跑实现者精确样例。至少使用不同日期、列组合和三表同时 coercion 反例；逐表证明公开 frame、
公开 digest 和重新计算值闭合，并复跑原初验 C1–C10 中 identity/Schema/result 相关变体。失败则再次返回实现
循环；通过后才可交主 Agent 终验。

## 6. 验证命令

全部由 Windows Cursor Agent 通过 `wsl.exe` 在 WSL Miniforge `base` 执行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_index_membership.py tests/unit/test_m3_identity.py \
  tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_mappers.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```
