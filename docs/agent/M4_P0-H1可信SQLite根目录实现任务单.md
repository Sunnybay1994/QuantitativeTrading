# M4 P0-H1 可信 SQLite 根目录与物理路径边界任务单

状态：**主 Agent 已冻结，可与 M4-B2 并行实现；不得重新宣称 P0/M4 Gate 通过**  
日期：2026-07-17  
环境：Windows 原生 `cursor-agent --model cursor-grok-4.5-high` 启动，项目命令仅在 WSL Miniforge `base` 运行  
默认：离线、临时目录、小型定向测试；禁止真实数据、token、券商、下单和全量 pytest

## 1. 目标与背景

已通过子包主验的 P0 只冻结了 SQLite URI 的 lexical relative contract。主 Agent 反例证明：当前
`ExecutionStore.open("sqlite:///link/db.sqlite")` 依赖 cwd，且 `link` 若为指向工作根外的 symlink，会在外部
物理目录创建数据库。P4 service 打开真实 store 前必须关闭这一边界。

本任务只加 trusted-root 和物理路径保护，不改变数据库 schema、repository、identity、事务或 migration。

## 2. 冻结 API

把公开入口改为：

```python
@classmethod
def open(cls, uri: str, *, trusted_root: Path) -> ExecutionStore: ...
```

- `trusted_root` 是强制 keyword-only 参数，不提供 cwd/default fallback；旧的无 root 调用必须 `TypeError`。
- URI lexical 规则保持现有 `_parse_sqlite_uri` 合同，不放宽任何绝对路径、drive、`..`、反斜杠、query、fragment
  或 percent encoding。
- `_parse_sqlite_uri` 应返回相对路径；实际路径只能由显式 trusted root 组合，禁止读取 `Path.cwd()`。

## 3. trusted root 合同

`trusted_root` 必须：

- 是当前 WSL 平台的标准 concrete `pathlib.Path`（可用 `type(value) is type(Path())` 判断；拒绝 str、bytes、
  bool、任意 `__fspath__` 伪装和自定义 concrete Path 子类）；
- 是绝对路径；
- 已存在、是目录、不是 symlink；
- 不是文件系统根本身；
- 可以 `resolve(strict=True)`，解析结果仍为目录。

任何失败统一抛：

```python
StoreUriError("TRUSTED_ROOT_INVALID")
```

不得包含 root/URI/OS 错误文本，`__cause__` 与 `__context__` 必须均为 `None`。

## 4. URI 物理边界

在任何 mkdir/sqlite open 前后执行稳定检查：

1. 从 trusted root 开始逐段检查 URI 的所有**现存**祖先；任何 symlink、非目录组件或解析后不在 resolved
   root 之下都拒绝；
2. 缺失祖先可由现有 store 行为创建，但每层创建后必须再次检查为真实目录、非 symlink、物理上仍在 root；
3. leaf 若已存在，必须是非 symlink 的普通文件，且 `st_nlink == 1`；目录、FIFO/device/socket、symlink、
   多硬链接均拒绝；
4. sqlite connect 返回后再次验证 parent 和 leaf；验证失败必须安全关闭连接，再抛稳定错误；不得静默保留可用
   store；
5. 本包采用“root 下禁止任何 URI 组件 symlink”的保守策略，即使 symlink 最终仍指向 root 内也拒绝；
6. 所有 containment 判断使用物理 resolved 路径，不做字符串 `startswith`。

路径/叶子边界失败统一抛：

```python
StoreUriError("URI_PHYSICAL_BOUNDARY_INVALID")
```

异常脱敏和空 cause/context 要求同 §3。不得删除既有文件，不得因验证失败清理用户预存 leaf。

本任务防止普通静态 symlink/hardlink/特殊文件逃逸；不宣称抵抗具有同账户并发重命名能力的恶意本地进程。
P4 仍需使用现有单进程/数据库锁与运行目录权限。

## 5. 测试要求

在现有 `tests/unit/test_execution_store.py` 内把所有合法 `ExecutionStore.open` 调用改为显式
`trusted_root=cwd_tmp` 或等价临时根；不得弱化既有 109 项。

至少新增：

- 缺少 `trusted_root`、相对 root、字符串 root、root symlink、root 文件、`/` 根；
- 中间 symlink 指向 root 外；
- 中间 symlink 指向 root 内仍拒绝；
- leaf symlink 指向外部文件；
- leaf 为目录、FIFO（平台支持时）、多硬链接；
- 已存在普通单链接数据库可正常打开；
- 缺失多层 parent 可在 root 内创建；
- 改变 cwd 后，同一 URI 仍只落在显式 trusted root；
- `Path.resolve`/`lstat`/mkdir/sqlite connect 或 connect 后复验抛含绝对路径的 OS 异常时，顶层稳定 code、
  message/repr/traceback 无绝对路径，cause/context 均为空；
- connect 后复验失败会关闭连接，不覆盖主错误；close 失败也不得泄露底层异常。

所有测试仅用 pytest `tmp_path`，不得读取项目 `data/` 或真实 store。

## 6. 文件白名单与并发边界

唯一实现写会话只允许修改：

- `src/quant/execution/store.py`
- `tests/unit/test_execution_store.py`
- `docs/agent/M4_P0-H1可信SQLite根目录交付报告.md`（新建）

禁止修改 `execution/config.py`、migrations、contracts、其他测试、任务书、README、路线图和任何 B2 文件。
本包与 B2 的读写集合互斥，可并行；不得读取正在由 B2 写入的目标文件。

全新独立初验会话只能写：

- `docs/agent/M4_P0-H1可信SQLite根目录独立初验报告.md`

初验不得与实现重叠，生产代码和实现测试只读。

## 7. 高效验证

实现者只运行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_execution_store.py -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/execution/store.py tests/unit/test_execution_store.py
/home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/execution/store.py
```

不得运行全量 pytest。报告只写摘要、修改文件、契约映射和限制，不附完整日志。

## 8. 独立初验未公开方向

独立初验必须至少增加三个实现者未使用的临时目录反例，其中包含：

1. 两层祖先中第二层 symlink 指向 root 外，leaf 尚不存在；
2. 已存在合法 DB leaf 在调用前被换成 hardlink，必须在 sqlite 产生经济写入前拒绝；
3. monkeypatch connect 后复验异常与 close 异常同时发生，主错误优先且异常链、traceback 均脱敏。

## 9. 通过条件

- public API 不再依赖 cwd，P0-H1 原 symlink escape 反例关闭；
- lexical URI、schema/migration/repository/事务既有合同保持；
- 定向 pytest/Ruff/mypy 通过；
- 外部实现后由全新只读外部会话初验，不通过则回实现者返工再复验；
- 外部会话不得勾选路线图、重新宣布 P0 或关闭 M4 Gate。
