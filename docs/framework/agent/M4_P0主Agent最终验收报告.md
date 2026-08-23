# M4-P0 主 Agent 最终验收报告

日期：2026-07-17  
结论：**M4-P0 子包最终验收通过**  
边界：不关闭 M4/Gate；只确认当前 SQLite store/migration 冻结合同

## 1. 闭环摘要

1. 原 P0 外部闭环后，主验发现绝对 URI、identity wire format、orphan event 和 I/O 脱敏缺口；
2. 第一轮外部返工关闭 URI/identity/FK，但独立初验发现 `from None` 没有清空 `__context__`，见
   [`M4_P0主验返工独立初验报告.md`](M4_P0主验返工独立初验报告.md)；
3. 第二轮实现把所有 OS/sqlite 映射改为离开原 `except` 后再抛稳定错误；
4. 全新外部 Agent 用预挂 cause、COMMIT+ROLLBACK 双失败和业务异常对抗，独立初验通过，见
   [`M4_P0主验二次返工独立初验报告.md`](M4_P0主验二次返工独立初验报告.md)；
5. 主 Agent 复跑定向、异常链反例和 M4 基础层合流。

## 2. 最终验证

```text
WSL Miniforge base
python -m pytest -q tests/unit/test_execution_store.py
→ 109 passed

M4 C0/D0/D1/P0/P1/P3 定向合流
→ 263 passed
```

外部实现与独立初验分别复跑目标 Ruff/mypy，均通过；未运行无关全量 pytest。

主 Agent 反例：

| 反例 | 结果 |
|---|---|
| parent 为普通文件导致 mkdir 失败 | `PARENT_CREATE_FAILED`；cause/context 均 None；traceback 无绝对路径 |
| mock sqlite connect 抛含路径 OperationalError | `OPEN_FAILED`；cause/context 均 None；traceback 无 token |

## 3. 最终判定

- SQLite URI 只接受 canonical 相对 POSIX 形式；
- durable identity 为裸 64 lowercase hex，损坏 row fail closed；
- event 必须引用已存在 command，同 key 同内容幂等、异内容 conflict；
- migration/version/transaction/close 使用稳定错误；cleanup 不覆盖主错；
- 映射错误的 cause、context、message/repr、traceback 均脱敏。

因此 M4-P0 当前冻结子包最终验收通过。

## 4. 已记录的非阻塞 P2（P4 前必须关闭）

主 Agent 临时目录探针得到 `RELATIVE_SYMLINK_ESCAPE_ACCEPTED True`：URI 字符串虽为合法相对路径，但其中已有
目录 symlink 可指向工作根之外，SQLite 会在外部物理目录建库。当前 P0 任务只冻结 lexical URI 合同，且 P4
service 尚未启动，因此本项不回退已通过的 URI/identity/FK/transaction 主流程；但在 P4 读取真实 store 配置前，
必须增加显式 trusted root 与 symlink/physical containment 合同，不能依赖调用进程 cwd。
