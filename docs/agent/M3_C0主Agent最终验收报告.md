# M3 C0 主 Agent 最终验收报告

日期：2026-07-13  
结论：**C0 通过主 Agent 最终验收**  
范围：唯一 M3 TOML loader、严格配置契约、九类配置身份、tracking target 与 C0D 调用边界  
不代表：M3 整体、E3 strict receipt、G1–G9、真实 Qlib 依赖、真实网络或实盘通过

## 1. 四段式交付链

| 阶段 | 产物 | 结论 |
|---|---|---|
| 主 Agent 设计/任务书 | [`M3实施与Agent交接.md`](../M3实施与Agent交接.md) 4.0、[`M3_C0配置加载与身份哈希实现初验任务单.md`](M3_C0配置加载与身份哈希实现初验任务单.md) | 冻结 151/138 闭包、九类 selector、URI/secret 安全域和调用边界 |
| 实现 Agent 首次交付 | [`M3_C0配置加载与身份哈希交付报告.md`](M3_C0配置加载与身份哈希交付报告.md) | 实现完成，但仅属自测交付 |
| 独立初验 | [`M3_C0配置加载与身份哈希独立初验报告.md`](M3_C0配置加载与身份哈希独立初验报告.md) | **不通过**：3×P1 + 1×P2 |
| 原实现 Agent 返工 | [`M3_C0配置加载与身份哈希返工交付报告.md`](M3_C0配置加载与身份哈希返工交付报告.md) | 四项安全边界最小修复并增加生产回归 |
| 独立复验 | [`M3_C0配置加载与身份哈希独立复验报告.md`](M3_C0配置加载与身份哈希独立复验报告.md) | **通过**：19 个独立反例全部通过，无新增问题 |
| 主 Agent 终验 | 本报告 | 代码/契约/证据链重算通过，关闭 C0 |

## 2. 初验问题如何转化为项目能力

| 初验发现 | 根因 | 最终规则/实现 | 主验结果 |
|---|---|---|---|
| 外层 message 脱敏，traceback cause 仍泄露物理路径 | 自测只检查 `str/repr` | 读取/解析私有边界吞掉值携带异常，公开边界无 cause/context 构造稳定 issue | I/O 与 parse sentinel 的 formatted traceback 均脱敏 |
| percent-encoded sensitive key 漏扫 | key/value 安全规范化管线分叉 | 唯一受控三层 decode primitive，unknown 之前先扫描 | 单/双/三层编码均拒绝，合法 SHA/URL 不误杀 |
| loader 与 direct tracking helper 安全域不一致 | public helper 手写不完整验证 | 共享 `_validate_safe_string`，对合法/非法 name 成对测试 | 两入口 accept/reject 一致，合法 target key 一致 |
| 非字符串 mapping key 在 strict validation 前被 `str()` | normalize 早于类型验证 | `_thaw` 保留原 key，遍历时先 `TYPE_ERROR`，后续只对已验证 key cast | int `1` 与 string `"1"` 不合并，非法 key 子树仍扫 secret |

上述经验已同步到 [`M3_C0配置设计审查记录.md`](M3_C0配置设计审查记录.md)，后续实现与验收 Agent
不应再把“正常路径绿测”当作公开信任边界已完整的证据。

## 3. 主 Agent 独立复核

主 Agent 逐段复核 `src/quant/research/m3/config.py` 的读取/解析、direct target、strict mapping key、
secret/path 管线和规范 JSON 边界，并确认：

- 返工只修改 `config.py`、`test_m3_config.py` 和报告，未改 selector、literal、示例配置、snapshot/fetcher 语义；
- 字段闭包仍为 151 assignments / 138 normalized shapes / 138 specs / 1 optional；
- M3 production 只有 `config.py` import `tomllib`；
- snapshot/fetcher 不含旧 `config_path/provider_format/DEFAULT_CONFIG_PATH/load_dump_script_spec`；
- `quant.data` 没有对 `quant.research` 的反向 import；
- 冻结 literal 依旧通过“公开拒绝+结构 selector 归属”验证，没有为制造 hash 变体而放宽 validator。

## 4. 主 Agent 实际执行的验证

所有 Python 和项目工具均由 WSL Miniforge base 执行。

| 验证 | 结果 |
|---|---|
| C0 针对性 pytest | `102 passed, 30 warnings` |
| 全量 pytest | `301 passed, 1179 warnings` |
| Ruff | `All checks passed` |
| mypy | `Success: no issues found in 71 source files` |
| C0D 源码搜索 | 唯一 M3 TOML reader；旧入口 0；data→research import 0 |
| 本地 Markdown 链接 | 项目根+`docs/` 41 份文档通过（本报告写入前检查） |

1179 个 warning 为既有 Pandera/Polars deprecation warning；WSL localhost proxy 提示与本次离线验收无关。
二者均未被计为通过证据，也未被误报为 C0 缺陷。

## 5. 最终裁决与剩余 blocker

C0 满足完成标准，可作为后续 M3 stage 的唯一配置与窄化身份入口。路线图只勾选 C0 子项，
不勾选 G0–G9 或 M3 整体。

仍然阻断后续门禁的项目：

1. E3 strict receipt、bare identity key 与 no-symlink 发布尚未返工验收；
2. G1 B2–B4 请求 journal、PIT membership、跨源对账和 immutable release 尚未交付；
3. G2 最终 session calendar/provider、G3 label reconciliation 和 G4–G9 尚未关闭；
4. WSL base 当前 Python 3.13.13，pyqlib/LightGBM/MLflow 真实依赖仍不可用；
5. C0 是离线配置验收，未读取 token、未联网、未执行真实 Tushare 或任何交易。
