# M3 E3 严格 Receipt 增量独立初验报告

日期：2026-07-13  
结论：**不通过；R1–R4 尚未交付，不能进入主 Agent 终验**  
任务书：[`M3_E3严格Receipt增量返工任务单.md`](M3_E3严格Receipt增量返工任务单.md)  
历史交付：[`M3_E0_E3交付报告.md`](M3_E0_E3交付报告.md)

## 1. 验证范围与结果

未参与实现的初验 Agent 只读检查 `run_state.py`、`contracts.py`、包导出和测试，并在系统临时目录增加
对抗性反例。现有历史报告准确描述的是首次 E3，不是严格增量交付；任务书要求的
`M3_E3严格Receipt增量返工交付报告.md` 尚不存在。

- 相关既有测试：35 passed；
- Ruff：通过；mypy 三个相关源码文件：通过；
- 主 Agent 全量基线：227 passed，Ruff/mypy 通过；
- 上述绿测编码的是旧契约，不证明 R1–R4。

## 2. P0 问题

### P0-1：严格 receipt 语言未实现

证据：`run_state.py` 的 `Scope/StageReceipt/json.loads/_digest_from_mapping/_canonical_receipt_bytes`。

当前没有 `receipt_version` 和 `ACCEPTANCE`；接受 duplicate 顶层/digest key、未知字段、NaN/Infinity、
`size_bytes="3"/true`、路径式 stage/key 和 inputs/outputs 交叉重复；canonical JSON 未显式
`allow_nan=False`。合法 ACCEPTANCE receipt 反而被拒。

根因：首次实现只验证自报文件 hash，没有先定义唯一、严格、版本化的 receipt 语言。

通过条件：发布/读取共用严格 validator；字段集合精确，duplicate/NaN/宽松转换/控制字符/交叉重复在文件
hash 前失败；v1 + ACCEPTANCE round-trip，旧无版本 receipt fail-closed。

### P0-2：root 与全路径 no-symlink 未实现

证据：`_digests_from_paths/_relative_posix_under_root/_resolve_under_root` 使用 `resolve()` 只防最终逃逸。

当前接受 root 自身、父目录、文件 symlink（即使指向 root 内），发布时还会把 symlink 路径改写为真实路径；
空 digest 时缺失 root 不检查。

根因：把“symlink 不逃逸”误当“路径链不得出现 symlink”。

通过条件：每个 root 先验证存在、目录、非 symlink；用 `lstat()` 或等价方法逐组件拒绝 symlink；最终必须
是普通文件，publish/verify 两条路径和空 digest 均覆盖。

### P0-3：snapshot/provider 边界仍是旧模型

证据：`contracts.DatasetSnapshot` 及现有 contracts/snapshot 测试仍要求 `provider_path`。

根因：首次 E3 把 provider 当 snapshot 内部路径，未迁移到独立 provider key/dir/receipt。

通过条件：字段、调用和测试同步移除 `provider_path`，不增加兼容 alias；snapshot identity 不受 provider
路径或 runtime 改变。

### P0-4：R4 身份接口缺失

当前 `compute_provider_key` 无 `provider_runtime_fingerprint_sha256`；
`compute_provider_validation_key/compute_label_reconciliation_key` 和包导出均不存在；identity helper 接受
非法 hash、空版本、空 fold、`horizon=True/0`。

根因：首次 E3 没有 provider runtime、validation、reconciliation 三个独立变化维度。

通过条件：签名与 SSOT 4.9 一致，并证明：LightGBM 只改 experiment/reconciliation；NumPy/pandas/Qlib
改 provider+experiment；validation 配置只改 validation/reconciliation；h=5/h=10 不同；非法输入全拒绝。

### P0-5：旧测试主动冻结旧格式

当前测试断言无版本 JSON、只测逃逸 symlink，并要求 `provider_path`。这不是偶然漏测，而是返工尚未开始。
必须迁移旧断言并增加任务书第 6 节全部反例，不能保留 35 passed 作为严格交付依据。

## 3. P1/P2

- 多个异常会输出 receipt/越界文件的本机绝对路径。错误应只含 alias+relative path，并测试不含 temp/workspace
  前缀，避免污染 CLI、日志和 MLflow。
- 返工完成后新增严格增量交付报告，保留首次报告为历史；更新 `run_state.py` 顶部 provider key 示例；如实
  披露单文件 replace 不等于跨文件事务及目录 fsync 平台限制。

## 4. 给实现 Agent 的反馈

不要逐个给反例打补丁。正确顺序是：先写严格 JSON object-pairs parser 和统一值 validator，再验证 root/
路径链，最后让 publish 与 verify 共用同一构造入口；身份函数用按参数角色区分的 hash/version/horizon
validator。这样新增字段不会再次出现“写端接受、读端拒绝”或两套规则漂移。

本轮初验未修改源码或测试，临时反例未写入项目。路线图、G8、G9 状态保持未通过。

