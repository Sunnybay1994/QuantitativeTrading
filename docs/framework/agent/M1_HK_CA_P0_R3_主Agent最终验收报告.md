# M1 HK-CA-P0 R3：主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（来源无关开发合同）**

## 范围

本报告验收 HK 公司行动 P0 的 retained-byte、revision、PIT/as-of 选版和进程内来源验证 capability。
它不验收任何真实 HK 数据源格式、许可、修订完整性、复权/total-return、HK60、M1 总 Gate 或 ext4。

直接证据：

- `M1_HK_CA_P0_来源无关PIT公司行动合同任务单.md` 第 16 节；
- `M1_HK_CA_P0_R2_来源无关PIT公司行动合同独立复验报告.md`；
- `M1_HK_CA_P0_R3_内容绑定AdapterAttestation返工交付报告.md`；
- `M1_HK_CA_P0_R3_内容绑定AdapterAttestation独立复验报告.md`。

## 主验结论

1. adapter-facing factory 只能创建 `adapter_parsed` projection，不含 attestation；selector 和 result verifier
   均拒绝直接消费该对象。只有 `verify_hk_corporate_action_source` 对 query、retained bundle、
   candidate 和 projection 执行 fresh exact 验证后才能签发 `source_verified` capability。
2. HMAC-SHA256 payload 精确绑定 source、adapter version、query identity、bundle identity、candidate table
   digest 和 projection digest。消费者先 fresh 重算公开闭包，再用 `compare_digest` 核对进程内 token。
3. R2 的 whole-rehash 旁路已关闭：修改 raw content/metadata/source issue/candidate/projection 并同步重算
   全部公开摘要后，旧 token 不能复用。独立复验进一步将旧 token 移植到另一合法 query、
   version、candidate set 和 source，4/4 均拒绝。
4. attestation 不进 projection repr/equality、pickle、`__all__`、artifact 或 log。模块 reload 后旧 capability
   fail closed，必须重新对 retained bytes 执行 source verification。
5. hostile adapter/HMAC 的已知和未知异常都在 active `except` 外重建为稳定码；cause/context 为
   `None`，traceback 不包含 marker。future withdrawal、tombstone、no-lookahead、revision chain 和 result
   fresh verifier 均保持。

## 验证

主 Agent 在 Windows 原生 Miniforge 使用全新 basetemp 重跑：

```text
test_schemas.py + test_hk_corporate_actions.py: 102 passed
Ruff: All checks passed
mypy: Success, 3 source files
```

独立复验者另外执行了实现者未使用的跨合法对象 token 置换、factory-only、hostile HMAC、
reload/pickle 与 withdrawal/tombstone 反例；Windows 与 WSL base `/mnt/f` 均为 102 passed，Ruff/mypy 均通过。
`/mnt/f` 是 DrvFS，仅是 WSL base 开发兼容证据，不是 ext4/Linux Gate。警告为已知 Pandera/Polars
deprecation 输出。

## 状态与后续

- HK-CA-P0 来源无关开发合同正式收口，可用于未来真实 HK adapter 与 PIT 选版工程。
- attestation 只是进程内 capability 绑定，不是外部数据源签名、跨进程证书或 WORM。
- 真实 HK source adapter 必须等合法 licensed bytes/spec 和 revision/withdrawal completeness 证据；本 P0
  不允许从未冻结格式猜字段。
- HK60 `01065.HK@2026-05-05`、HK ETF 来源、真实复权/total-return、U0C 自然日程与 ext4
  仍是 M1 未关闭项。

本轮未联网、未读取凭据、未修改正式数据/journal/HK60/U0C/G1，未执行 `git add/commit`。
