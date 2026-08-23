# M4 P0-H1 主 Agent 最终验收报告

日期：2026-07-17  
结论：**P0-H1 trusted-root 与静态物理路径边界最终验收通过**  
边界：不重新定义 P0 其他合同，不代表 P4 或 M4 Gate 通过

## 1. 闭环证据

- 冻结任务：[`M4_P0-H1可信SQLite根目录实现任务单.md`](M4_P0-H1可信SQLite根目录实现任务单.md)
- 外部实现：[`M4_P0-H1可信SQLite根目录交付报告.md`](M4_P0-H1可信SQLite根目录交付报告.md)
- 全新外部只读初验：[`M4_P0-H1可信SQLite根目录独立初验报告.md`](M4_P0-H1可信SQLite根目录独立初验报告.md)
- 原风险：[`M4_P0主Agent最终验收报告.md`](M4_P0主Agent最终验收报告.md) §4

外部初验独立复跑 130 项，并增加两层祖先 symlink、合法 DB 换 hardlink、connect 后复验与 close 双失败三类
实现者未用反例；全部通过且异常脱敏。

## 2. 主 Agent 复核

代码审查确认：

- `ExecutionStore.open(uri, *, trusted_root)` 强制显式 keyword-only root，不再调用 cwd；
- lexical URI parser 只返回相对 `Path`，未放宽原绝对路径/穿越/query/fragment 等拒绝；
- trusted root 必须为 WSL 标准 concrete Path、绝对、已存在目录、非 symlink、非文件系统根；
- URI 祖先逐段 lstat/resolve/relative_to，所有 symlink（包括仍指向 root 内）均 fail closed；
- leaf 只接受单硬链接普通文件，connect 后再次检查 parent/leaf，失败安全关闭连接；
- OS/sqlite 映射在离开原 except 后抛稳定 code，cause/context 和 traceback 不回显路径。

主 Agent 定向验证：

```text
python -m pytest tests/unit/test_execution_store.py -q
→ 130 passed in 4.80s
```

主 Agent 另建临时 root：真实第一层目录下的第二层 symlink 指向 root 外，URI leaf 尚不存在。结果：

```text
P0H1_MAIN_ESCAPE_REJECTED
```

即 `URI_PHYSICAL_BOUNDARY_INVALID`，cause/context 为空，错误无临时绝对路径，外部目标未生成数据库。

## 3. 最终边界

P0-H1 已关闭原 `RELATIVE_SYMLINK_ESCAPE_ACCEPTED` 风险，P4 后续可以把显式应用运行目录作为
`trusted_root` 传入，但仍须满足 P4 自身 outbox/恢复前置。

本包按任务书只防静态 symlink、hardlink、特殊文件和普通物理逃逸，不宣称抵抗具有同账户并发 rename 权限的
恶意本地进程。该限制已披露，不阻断个人 PAPER/SHADOW 单进程 M4 路线。

