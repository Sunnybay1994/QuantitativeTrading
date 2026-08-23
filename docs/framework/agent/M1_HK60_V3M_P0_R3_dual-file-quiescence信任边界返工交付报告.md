# M1-HK60-V3M-P0 R3 dual-file quiescence 信任边界返工交付报告

日期：2026-08-09
结论：**R3 实现与自测 PASS，待全新独立复验和主 Agent 最终验收**

## 1. 现象、根因与重冻规则

R2 已能拒绝单个 retained 文件在自身最终 held-instance 观测前保留的可观察内容漂移，但两个外部可写文件的
有限顺序检查不存在共同的最后观测瞬间：raw 最终复读后、metadata 最终复读期间仍可原地改写 raw。继续增加
固定扫描轮次、交换顺序、重开路径或检查 mtime 均不能证明两个路径在共同瞬间不可变。

R3 因此诚实冻结信任模型：retained raw/metadata 必须由上游 write-once/no-clobber materializer 发布，caller
必须保证从 loader 开始到下游 finalize 消费 exact returned bundle 完成期间没有并发 writer。loader 保证首读
bytes 来自 anchored open instance、每个文件在自己的最终 held-instance 观测点仍与首读 length/SHA 和身份一致，
且下游只消费由首读 bytes 验真的 cached bundle；它不独立抵抗违反该 quiescence 前提的 retained-root writer。

## 2. 最小改动

- `load_verified_hkex_retained_bundle_for_finalize` docstring 明确 write-once/no-clobber 与 caller quiescence 前提、
  逐文件保证和双路径共同瞬间的非保证。
- CLI 模块 docstring 同步说明 v3 finalize 的信任边界；CLI 行为、参数、失败码和输出 wire 均未改变。
- loader 层新增 cross-file interleave 反例：在 raw 最终观测后、metadata 最终观测期间真实原地改写 raw；断言
  返回值仍是 verifier 对首读 raw/metadata 生成的 exact bundle，同时最终 raw path 已不同。测试名称与注释明确
  writer 在冻结前提之外，不把接受表述成安全成功。
- CLI 层新增互补回归：模拟 loader 返回后违反 quiescence 的 writer，断言 finalize 只收到 exact returned
  bundle，不收到 raw/metadata 参数，也不按 path 重读输入。

R2 的 persistent raw/metadata drift 拒绝、真 ABA 语义对照、held reread、offset 恢复、same-open-instance、
hostile exception、symlink/reparse/hardlink、path replacement、legacy v2、partial/no-clobber 测试全部保留。
未增加锁、轮询、固定多轮 sweep、mtime/ctime、watcher、签名、caller boolean/capability，也未修改 parser、
schema、finalize 业务、正式数据、plan、journal 或配置。

## 3. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`：

- 两个新增定向测试：`2 passed`；
- 两个白名单测试文件：`132 passed, 2 skipped`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- cold-import no-network：`WINDOWS_R3_COLD_IMPORT_NO_NETWORK_PASS`。

WSL Miniforge `base`，同一 `/mnt/f` 工作树：

- 两个白名单测试文件：`134 passed`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- cold-import no-network：`WSL_R3_COLD_IMPORT_NO_NETWORK_PASS`；
- 文件系统类型：`wslfs`，仅属 WSL/DrvFS 开发证据，不是 WSL2/ext4 Gate。

`git diff --check` PASS。测试只使用隔离临时目录；未发起 HKEX、Tushare、BaoStock 或其他网络请求，未运行
真实 plan/recovery/finalize，未读写正式 HK60 raw、clean、journal 或候选目录，未 add/commit，并保留所有无关
脏文件。

## 4. 交付边界与后续

R3 PASS 只表示 fixture-only v3 CLI 在上述 write-once/no-clobber + caller quiescence 信任模型下完成实现自测。
cross-file interleave 反例仍是正式公开边界：拥有 retained root 写权限且违反 quiescence 的 writer 未被本 loader
技术阻止。未来 V3M-P1 execution manifest 必须绑定 write-once materializer 来源与执行期 quiescence；若需抵抗
此类 writer，应另立 retained materializer、OS policy 或独立信任锚合同。

本交付不解锁 02983 provenance materialize、01065 licensed source-freeze/verifier 或 formal V3M-P1，也不表示
HK60、HK 复权、M1 或 ext4 Gate 已通过。下一步是由未参与 R3 实现的全新上下文进行独立复验，随后由主 Agent
最终验收。
