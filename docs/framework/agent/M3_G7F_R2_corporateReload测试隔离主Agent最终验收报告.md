# M3 G7F R2：corporate reload 测试隔离主 Agent 最终验收报告

日期：2026-08-10  
结论：**PASS；G7F 三场景回测 Artifact 工程合同完成，允许实现 G8；不等于 ext4 或 M3 Gate。**

## 验收结论

G7F R1 production、双平台定向与独立 hostile Decimal、29-output整包合法重签、21/29 receipt、nested tree和
异常图对抗均通过，但强制邻接因corporate-actions cold-import测试在父pytest进程原地reload production而出现
`148 passed / 5 failed`。reload使G7E持有的旧class/enum identity与旧函数globals中的新identity分裂，formal
exact边界正确自拒绝。

R2仅把该cold-import/reload断言移入fresh `python -I`子进程；父pytest不再reload production。子进程继续验证
qlib/lightgbm/mlflow未加载、exact public surface、私有issuer不可达、旧state/transition在reload后拒绝、新
capability与transition可用。G7F production、G7E simulator与两个G7F测试均未修改。

全新独立复验使用实现者未用的固定顺序：cold→G7E ex-date→row-order→G7E golden→G7F build/verify→
whole-bundle→G7F golden，Windows/WSL各`7 passed`；正确原8文件原顺序单进程双平台各`153 passed`；G7F
unit+golden双平台各`10 passed`；Ruff、mypy、fresh cold、diff-check均PASS。独立报告如实排除了误选相似plan
测试产生的147项无效结果。

主 Agent 对最终revision重跑cold→G7E ex-date→hostile Decimal→golden：Windows/WSL各`4 passed`，定向Ruff与
mypy均PASS。冻结SHA-256确认：

- `a_share_reporting.py`：`698937E25AE69505497565FE65722E4E694AE2B7B00E50ECF0370332085B3A81`
- `a_share_simulator.py`：`2E123BC293137B468307BD64BD8EDE2F4BBBCED0BA48B487596461F235605406`
- G7F unit：`B3A28FEC24D63F02E259FD1A11E9779B04976976C0EF9986718A0E9B81866A3E`
- G7F golden：`3B13FE167E8586E014EC530C578E2E853D9D513E1EA36CAACAF1B639E2F150CE`
- R2 corporate test：`F104E8FE7E831B1CE479F7431DB685E49F9B3221D6145A2A10C59FF75C9FE3C6`

WSL路径仍为`/mnt/f`/DrvFS。未联网、未add/commit、未触正式artifact/receipt。
