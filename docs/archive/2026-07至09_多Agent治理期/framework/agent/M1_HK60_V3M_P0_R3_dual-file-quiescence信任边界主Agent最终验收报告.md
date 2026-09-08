# M1 HK60 V3M-P0 R3 dual-file quiescence 信任边界主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（fixture-only 工程合同）**

## 1. 结论

显式 `--finalize-v3` 外壳已在诚实、可实现的信任模型下完成闭环：retained raw/metadata 由上游
write-once/no-clobber materializer 发布，调用者保证从 loader 开始到 finalize 消费 exact returned bundle 完成
期间没有并发 writer。loader 保留 anchored open-instance、逐文件 held reread、length/SHA、namespace与物理身份
复核；CLI 唯一把首读 bytes 生成的 exact verified bundle 交给 finalize，不再次按 path 读取。

本结论明确不声称两个外部可写路径在共同瞬间不可变，也不抵抗拥有 retained root写权限且违反 quiescence 的
writer。R2 的 cross-file interleave 反例被保留为公开信任边界，未用增加扫描轮数、mtime或伪锁掩盖。

## 2. 主验核对

- loader/CLI docstring、任务与报告均明确 write-once + quiescence 前提和非保证；
- raw/metadata 单文件 persistent same-inode drift仍由held-instance复读拒绝；真ABA只在exact语义输入/输出均未变
  时作为不可观测边界允许；
- cross-file interleave测试真实修改同一文件，证明返回bundle仍是verifier首读exact内容，而final path可不同；
- CLI互补测试证明finalize只消费returned bundle，不接收raw/metadata参数、不按path重读；
- R2 open-instance、offset恢复、hostile异常、legacy v2、partial/no-clobber与冷导入回归全部保留。

## 3. 验证证据

实现与全新独立初验：

- Windows：`132 passed, 2 skipped`；Ruff、mypy、cold import、公共边界断言 PASS；
- WSL base：`134 passed`；Ruff、mypy、cold import、公共边界断言 PASS；
- Windows白名单 `git diff --check` PASS；WSL worktree `.git` 指向Windows路径而无法独立执行git命令，该工具
  路径边界未被表述为测试通过；
- 当前WSL为wslfs/DrvFS，不是ext4 Gate。

主 Agent 定向复核：cross-file interleave与CLI bundle-only两个测试 → `2 passed`；四个白名单文件 Ruff PASS；
两个生产文件 mypy PASS。

## 4. 未关闭事项

- fixture-only外壳通过不生成正式02983 metadata，不取得licensed 01065 issue/spec，也不创建formal V3M-P1
  plan/journal/root。
- 正式V3M-P1 execution manifest仍须绑定上游write-once materializer来源与执行期quiescence；若要抵抗违反
  前提的writer，必须另立OS policy/独立信任锚合同。
- HK60、HK复权、M1、Linux/ext4 Gate仍开放；未联网、未触正式data/journal、未add/commit。
