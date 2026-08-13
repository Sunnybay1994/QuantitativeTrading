# M1-HKEX-02983-P0 Daily Quotations 返工独立复验报告

日期：2026-08-02（Asia/Shanghai）

角色：原独立 reviewer 同一人返工复验
结论：**PASS（第二次返工复验），可进入主 Agent 终验**

## 第二次返工复验结论

- `VerifiedHKEXDailyQuotation.__init_subclass__` 现会在类创建阶段拒绝所有子类。独立验证覆盖普通
  class、覆盖 `__new__`、覆盖 `__init__` 并尝试写入实例 `__dict__`，以及 `types.new_class` 动态创建；
  均在产生 capability 前稳定失败。
- 公开基类 constructor 继续稳定失败；公开 verifier 与兼容入口只接受 raw bytes，并 fresh 执行
  hash、parse、identity 与 sales-to-quotation closure。合成 raw、单字节篡改 retained raw、传入 Parsed
  代替 bytes 均不能通过。
- 正式 retained raw 产生的对象满足 `type(value) is VerifiedHKEXDailyQuotation`，没有实例
  `__dict__`，普通字段赋值失败。模块外 consumer 审计未发现任何消费者；当前不存在依赖宽松
  `isinstance` 或私有构造函数的旁路。

## 已关闭部分

- `verify_hkex_daily_quotation` 与兼容入口现在只接受 raw bytes，并在内部重新计算 digest、严格 parse、
  fresh 重建 Parsed、执行 volume/OHLC/last price/ROUND_HALF_UP turnover 闭包。
- 自洽合成 raw 即使将 Parsed 的官方 hash/size 及 `parsed_id/evidence_id` 全部重算，也不能经公开
  `VerifiedHKEXDailyQuotation(...)` 构造或两个 raw-bytes verifier 成为 Verified。
- 身份自洽但 `sales_volume != volume` 的 Parsed 同样不能经这些入口通过。

## 第一次返工历史问题：覆盖 `__new__` 的公开子类曾可伪造 capability

### 现象

第一次返工时，公开基类在 `VerifiedHKEXDailyQuotation.__new__` 中检查具体内部子类与 seal；当时测试只覆盖未覆盖
`__new__` 的普通子类。独立反例定义：

```python
class OverrideNew(VerifiedHKEXDailyQuotation):
    def __new__(cls):
        return object.__new__(cls)
```

随后可向实例写入重算后的 `evidence_id/evidence`。所得对象满足
`isinstance(value, VerifiedHKEXDailyQuotation)`。合成 raw 冒充官方 hash/size 的自洽 Parsed 可被装入；
将 `sales_volume` 改为 681、`volume` 保持 680 并重算全部 identities 的不闭合 Parsed 也可被装入。

### 根因

第一次返工的公开基类允许继承且没有 `__init_subclass__` 封闭规则。子类能够覆盖基类的 `__new__` seal 检查；
子类默认获得实例 `__dict__`，因此还能写入看似完整的 evidence 字段。若消费者按公开返回注解使用
`isinstance` 接受能力对象，无法区分该伪造对象与内部合法实现子类。

### 第二次返工关闭证据

公开类型现为 exact、final、slots-only capability；内部 factory 在 fresh 验真后创建 exact type，且返回前
再次复核 exact type 与 evidence identity。新增测试覆盖子类覆盖 `__new__`、自定义 `__init__`、尝试获得
`__dict__` 后写字段，以及重算全部 identities 的闭包/非闭包合成 Parsed；这些公开路径均稳定失败。

## 正向证据与双平台验证

- 真实 retained raw 在 Windows 与 WSL base 均保持：32,792,632 bytes，SHA-256
  `67d1109fe358021543579a6cb5f26c2a31c47f8feae6543e451f8356efcec5b8`，944 笔，volume
  2,640,331，sales turnover 43,420,387.430，evidence ID
  `c46f614dcea919b7beb4aaddd7a03e4b801dcb937e40d3262124d019b264f4da`。
- Windows Miniforge：Ruff PASS；mypy PASS；pytest `23 passed`。
- WSL Miniforge base：Ruff PASS；mypy PASS；pytest `23 passed`。
- 真实 raw 验真只读且无网络；`git diff --check` PASS。

第二次返工已覆盖第一次复验发现的 capability 子类反例。本 PASS 只表示 M1-HKEX-02983-P0 工程包满足
冻结合同并可进入主 Agent 终验；不表示 HK history、HK60、M1 或任何 formal Gate 已关闭。
