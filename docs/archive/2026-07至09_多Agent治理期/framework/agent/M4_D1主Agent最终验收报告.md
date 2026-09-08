# M4-D1 主 Agent 最终验收报告

日期：2026-07-16  
结论：**M4-D1 子包最终验收通过**  
边界：不关闭 M4/Gate；只确认 data repository 端口适配与错误边界

## 1. 闭环链路

1. 原交付和初验完成后，主验发现 key/content 混配、truthy 非 bool、畸形 bundle 非合同异常与 reader 路径泄漏，
   见 [`M4_D1主Agent终验报告.md`](M4_D1主Agent终验报告.md)；
2. 外部实现按 [`M4_D1主验返工任务单.md`](M4_D1主验返工任务单.md) 完成 F1–F3；
3. 全新外部 Agent 独立复现四个主验反例，并增加 account 反向 key、naive key、错误 value 类型和预挂异常链
   对抗，全部通过，见 [`M4_D1主验返工独立初验报告.md`](M4_D1主验返工独立初验报告.md)；
4. 主 Agent 在当前工作树复跑定向测试并抽查新增断言与实现边界。

## 2. 最终验证

```text
WSL Miniforge base
python -m pytest -q tests/unit/test_execution_ports.py
→ 16 passed
```

外部实现与独立初验分别复跑目标文件 Ruff/mypy，均通过；本次未机械重复全量 pytest。

主 Agent 代码与测试抽查确认：

- in-memory repository 在构造阶段验证 key 类型、key/content 绑定和 snapshot identity；
- clean bundle 的公开构造及 repository 消费前均执行 exact-type 门禁，`1/0` 不冒充 bool；
- reader 与 domain 异常映射为稳定 `RepositoryContractError.code`，不回显源异常文本；
- 映射异常在 `except` 外抛出，`__cause__` 与 `__context__` 均断开，traceback 不包含注入路径；
- 未捕获 `BaseException`，未修改 D0/P0/P1/P3 或领域合同。

## 3. 最终判定

主验的四个缺口及独立初验新增异常链变体均已关闭，定向回归通过。M4-D1 子包最终验收通过。该结论仅建立
M4 data port 的可信前置，不代表 store、OMS、risk、service 或交易 Gate 已完成。
