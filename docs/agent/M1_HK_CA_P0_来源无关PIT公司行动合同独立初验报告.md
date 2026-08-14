# M1-HK-CA-P0 来源无关 PIT 公司行动合同独立初验报告

日期：2026-08-09（Asia/Shanghai）  
角色：未参与实现的独立初验 Agent  
结论：**FAIL**

## 1. 初验范围与边界

只读检查了 `AGENTS.md`、`.ai` 通用规则、任务单、剩余阻断审计、实现交付报告、领域 schema、`hk_corporate_actions.py`、定向测试，以及被复用的 A 股 raw-first / revision-chain 结构边界。生产代码与实现测试未修改；未联网，未读取 connector、token、正式数据、journal 或候选目录。本报告是唯一写入。

实现的总体方向符合任务书：来源无关的 retained-bytes-only Protocol、HK 专属 canonical/evidence schema、PIT 选版、四类行动互斥字段、稳定错误码以及 result fresh rebuild 均已存在；模块没有 import/call connector，也没有复用 `.SH/.SZ`、CNINFO 字段或 A 股账户/复权语义。但以下两项高风险闭包被新增对抗反例击穿，因此不能进入主验。

## 2. 阻断问题

### F1：retained raw bytes 并未在消费者入口 fresh 重哈希

- 现象：创建合法 projection 后，用 `object.__setattr__` 将 `projection.bundle.files[0].content` 改为不同 bytes，再调用 `select_hk_corporate_actions`，返回成功，输出 `RAW_DRIFT_ACCEPTED`。
- 根因：`HkCorporateActionRawFile.__post_init__` 只在初次构造时重算 content/metadata digest；`_validate_bundle`（`src/quant/data/hk_corporate_actions.py:738`）只验证文件对象类型、声明摘要排序及 bundle 声明摘要，没有重新计算每个 retained file 的 `sha256(content)` / `sha256(metadata)`。随后 bundle/projection digest继续绑定旧声明摘要，因此 whole projection fresh verification 看不到底层 bytes 漂移。
- 违反规则：任务单要求 retained raw file、metadata、bundle、projection 均 fresh digest 闭包，selector 不能因冻结类型名而信任内容；raw 不可覆盖与来源证据闭包是本包核心不变量。
- 最小复现：

  ```python
  projection, _ = _projection(datetime(2026, 5, 7, tzinfo=UTC))
  object.__setattr__(projection.bundle.files[0], "content", b"TAMPERED RETAINED BYTES")
  select_hk_corporate_actions(projection=projection)  # 当前错误地成功
  ```

- 必须新增测试：分别篡改 `content`、`metadata`，并覆盖 selector 与 result verifier 的消费者入口；均应稳定返回 `HK_CA_EVIDENCE_INVALID`，且 `cause/context` 不泄漏原始内容。
- 通过条件：公共 fresh 验证路径逐文件重算 bytes/metadata SHA-256，再验证 bundle、candidate raw identity、projection；上述篡改全部 fail closed，正常重放摘要不变。

### F2：hostile adapter 异常可经 `__context__` 泄漏

- 现象：adapter 在捕获 `RuntimeError("SECRET_SENTINEL")` 后抛出合法 `HkCorporateActionError("HK_CA_EVIDENCE_INVALID")`；`verify_hk_corporate_action_source` 对该稳定错误直接 `raise`。边界最终错误虽为稳定码，但 `error.__context__ == RuntimeError("SECRET_SENTINEL")`，内部敏感文本仍可被调用方读取。
- 根因：`verify_hk_corporate_action_source`（`src/quant/data/hk_corporate_actions.py:330`）的 `except HkCorporateActionError: raise` 保留 adapter 构造的异常链；只对非合同异常使用 `raise ... from None`，没有把 adapter 边界产生的合同异常也规范化为无链的新异常。
- 违反规则：任务单明确要求所有公开边界异常脱敏，`__cause__ is None` 且 `__context__ is None`；hostile adapter 是指定必测反例。
- 最小复现：

  ```python
  class Hostile:
      source = SOURCE
      capability = capability
      def verify_retained(self, *, query, bundle):
          try:
              raise RuntimeError("SECRET_SENTINEL")
          except RuntimeError:
              raise HkCorporateActionError("HK_CA_EVIDENCE_INVALID")

  error = capture(verify_hk_corporate_action_source, adapter=Hostile(), ...)
  assert error.__context__ is None  # 当前失败，实际含 SECRET_SENTINEL
  ```

- 必须新增测试：hostile adapter 分别直接抛未知异常、从活跃异常中抛每个允许的合同错误码；公开入口最终只保留允许码，消息不含 sentinel，且 `__cause__`、`__context__` 均为 `None`。
- 通过条件：adapter 调用返回后/失败后的规范化在活动 `except` 之外抛出新的稳定错误；上述异常链对抗全部通过。

## 3. 其余合同证据

以下项目在代码审查、既有测试或新增内存对抗中符合任务单，不能抵消 F1/F2：

- future correction 在 `published_at` 前不改变历史 `as_of`；future withdrawal 在生效前保留 ACTIVE，生效后仅 selected tombstone 且 canonical 删除。
- selected tombstone 与 canonical action 的闭包由 verifier 重新构建；action/evidence/声明 digest 或 whole-result 行漂移会返回 `HK_CA_RESULT_INVALID`。
- revision 从 1 连续、predecessor 精确指向前一 candidate；缺口、错前驱、跨 event、event key/symbol/action 漂移和相同 `published_at` 冲突均 fail closed。
- `source + source_revision_id` 全表唯一；相同 revision identity 的重复/不同候选内容不能形成合法连续链。
- query/capability/symbol/date/action/currency scope、raw selector 和候选列集合均严格检查；fixture adapter 对未知 record/field 与不完整 metadata fail closed，capability 不足时 adapter 调用次数为 0。
- DIVIDEND/BONUS/SPLIT/RIGHTS 的字段分支互斥，CNY/HKD 只用于 DIVIDEND/RIGHTS；SPLIT 使用 post/pre multiplier，未复用 A 股现金/送转语义。
- 生产模块只依赖领域枚举/schema 与公共 table hash，不 import connector、requests、Tushare、AKShare、BaoStock、CNINFO、回测、账本、复权或 total-return 模块；没有路径发现、网络请求或正式数据写入。

## 4. 实际验证

Windows 原生 Miniforge：

- `pytest tests/unit/test_schemas.py tests/unit/test_hk_corporate_actions.py -q -p no:cacheprovider --basetemp artifacts/test-tmp/hk-ca-p0-review-win`：`67 passed`。
- 定向 Ruff：`All checks passed!`。
- 定向 mypy：`Success: no issues found in 3 source files`。

WSL Miniforge base，同一 `/mnt/f/.../m1-hkex-02983` worktree：

- 同一定向 pytest：`67 passed`。
- 定向 Ruff：`All checks passed!`。
- 定向 mypy：`Success: no issues found in 3 source files`。

独立对抗命令（Windows，纯内存、零网络）：

- retained bytes 构造后漂移：`RAW_DRIFT_ACCEPTED`，失败证据确认 F1。
- hostile adapter 活跃异常链：`HOSTILE_ERROR HK_CA_EVIDENCE_INVALID CAUSE None CONTEXT RuntimeError('SECRET_SENTINEL')`，失败证据确认 F2。

WSL 路径位于 `/mnt/f` DrvFS；以上只证明双平台开发反馈，不是 Linux/ext4 Gate。现有定向套件全绿，但新增对抗证明合同仍不闭包。

## 5. 结论与返工门槛

**FAIL**。必须先修复 F1、F2，并把上述最小复现固化为实现者测试；随后由未参与返工实现的新独立 Agent 重新复验。P0 当前不得表述为合同通过，更不代表真实 HK 来源、复权/total-return、HK60、M1 或 Linux/ext4 Gate 通过。
