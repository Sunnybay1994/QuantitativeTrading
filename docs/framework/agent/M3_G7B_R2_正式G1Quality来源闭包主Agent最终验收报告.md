# M3 G7B R2：正式 G1 Quality 来源闭包主 Agent 最终验收报告

日期：2026-08-10  
结论：**工程主验 PASS；仅解锁 G7F 同类来源闭包返工。**

formal G7B 的 19-input exact set 已改为 G1 manifest、G1 quality、G1 eligible，随后 G7A 冻结输入、target
四项和 trade calendar。quality path/sha/freshness 绑定与 G7A R3 一致；development receipt 路径保持不变。

证据：外部实现 Windows/WSL 组合各 111 passed；全新外部独立初验两平台各 111 passed，并完成 quality 与
target/calendar hardlink、旧伪 receipt 整包重签、根外 quality alias、G1 whole-root 替换和 hostile 异常脱敏
六组对抗。主 Agent 运行 R2 关键闭环节点 1 passed，Ruff/mypy PASS；scoped diff-check PASS。

本结论不覆盖真实全折、Linux/ext4、G7F/G8 或 M3 Gate。G7F/G8 仍必须各自修复同源输入合同并重新完成
外部实现、全新外部独立初验和主验。
