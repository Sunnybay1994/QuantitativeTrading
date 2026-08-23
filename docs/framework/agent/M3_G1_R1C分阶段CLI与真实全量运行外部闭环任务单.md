# M3 G1-R1C 分阶段 CLI 与真实全量运行外部闭环任务单

日期：2026-07-15  
状态：**R1C-A CLI 已通过主验；R1C-B 零网络预检完成，等待用户按资源清单授权真实阶段；R1C-C 受当前内核 `RENAME_NOREPLACE=false` 阻塞**  
代码实现模型：非 fast `cursor-grok-4.5-high`  
真实长运行：同一实现会话完成；独立初验使用全新 Grok High 会话

## 1. 目标

R1C 为已通过 R1L/R1B 的工作流增加唯一 CLI，并按阶段运行真实 2016–2026 G1 数据闭环。代码实现和真实
运行仍分开报告：

1. CLI/failure/output 合同和 fake 测试先通过外部实现—独立初验—主验；
2. 再由实现 Agent 使用已验收 CLI 执行真实 `INDEX → HISTORY → REFERENCE → PREPARE`；
3. 当前 WSL1 若不支持 `RENAME_NOREPLACE`，真实运行停在 PREPARE 并保留完整可恢复证据；PUBLISH 必须等
   支持内核，不得降级。

R1C 完成 PREPARE 仍不等于 G1 Gate；只有支持内核正式 publish、主 Agent 验真 release 且同步 SSOT 后才可
判断 G1 是否关闭。

## 2. 文件范围

代码阶段：

```text
src/quant/research/m3/run_g1.py
tests/unit/test_m3_run_g1.py
README.md                                      # 只新增唯一 CLI 使用说明和 WSL/base 命令
docs/M3_G1_R1C分阶段CLI交付报告.md
docs/M3_G1_R1C分阶段CLI独立初验报告.md
```

真实运行允许 R1B 固定布局产生：

```text
data/raw/m3_g1/**
data/run_state/m3_g1/**
data/clean/m3_g1/releases/**                  # 仅支持内核 publish 时
docs/M3_G1_R1C真实全量运行交付报告.md
docs/M3_G1_R1C真实全量运行独立复验报告.md
```

不得修改 token/config、既有数据合同、路线图勾选项或其他 clean/raw。

## 3. 唯一命令入口

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  <status|index|history|reference|prepare|publish|run-all>
```

公共参数只有：

- `--config`：必须显式给出项目内普通非 symlink TOML；
- `--project-root`：测试用途，默认当前工作目录；生产文档不要求用户填写；
- `run-all --stop-after {INDEX,HISTORY,REFERENCE,PREPARE,PUBLISH}`，默认 `PREPARE`。

禁止 `--token`、`--raw-root`、`--journal-root`、`--release-root`、自由 rate/threshold/version 覆盖。所有业务值
来自 C0；token 只由既有本地配置加载。

`status/prepare/publish` 不实例化 Tushare/BaoStock connector。`index/history` 只实例化 Tushare；
`reference` 只实例化 BaoStock；`run-all` 到达对应阶段时才实例化，前置失败不得提前登录或触发 SDK import。

## 4. 命令停止点

| 命令 | 必需前置 | 允许网络 | 成功后严格停止 |
|---|---|---|---|
| `status` | config/source context | 无 | 只返回当前 verified 前缀 |
| `index` | 无 | Tushare | INDEX |
| `history` | INDEX | Tushare | HISTORY |
| `reference` | HISTORY | BaoStock | REFERENCE |
| `prepare` | REFERENCE | 无 | PREPARE，输出 release identity |
| `publish` | PREPARE + 内核支持 | 无 | PUBLISH |
| `run-all` | 无 | 按需 | `--stop-after` 指定阶段 |

调用较后命令不自动补前置；只有 `run-all` 自动顺序推进。单段命令前置不完整必须返回对应稳定错误，不偷偷
回补。`run-all` 重跑通过 R1B inspect 复用全部已完成阶段。

## 5. 规范 stdout

成功、未完成 status 和失败均只向 stdout 写一行严格 JSON；日志只向 stderr 写稳定 code。stdout schema：

```python
@dataclass(frozen=True)
class G1CliResultV1:
    schema_version: Literal["m3-g1-cli-result-v1"]
    command: Literal["status", "index", "history", "reference", "prepare", "publish", "run-all"] | None
    outcome: Literal["SUCCESS", "INCOMPLETE", "FAILED"]
    completed_stages: tuple[Stage, ...]
    index_requests: int
    history_requests: int
    reference_requests: int
    history_symbols: int
    primary_candidate_key: str | None
    release_id: str | None
    manifest_sha256: str | None
    error_code: str | None
    error_operation: Operation | None
```

JSON 使用 UTF-8、键排序、紧凑 separators、`allow_nan=False`。不得输出路径、elapsed time、PID、host、用户名、
完整配置、receipt 内容、数据样本或 exception message。`status` 在合法但尚未完成时退出 0、outcome
`INCOMPLETE`；其他命令只有到达停止点才 SUCCESS。

argparse 尚未得到合法 command（缺失、未知 command、未知全局参数）时，`command=None` 是唯一合法形式；
一旦 parser 识别合法 command，后续失败必须保留该 literal。结果对象自证：stage 前缀、identity 字段出现
条件、成功/失败字段互斥、digest 裸 hex。写 stdout 前对序列化
bytes 做递归敏感模式扫描；命中则不输出原 bytes，改为稳定 `OUTPUT_REDACTION_FAILED`。

## 6. 退出码

```text
0  成功、合法复用，或 status 的合法 INCOMPLETE
2  argparse / config / project-root / output contract
3  source context / identity / journal 损坏
4  Tushare INDEX/HISTORY 失败
5  BaoStock / cross-source REFERENCE 失败
6  candidate/audit/PREPARE quality 失败
7  PUBLISH unsupported、冲突或 IO 失败
```

CLI-only error code 固定为：

```text
CLI_ARGUMENT_INVALID
CLI_CONFIG_INVALID
CLI_INTERNAL_ERROR
OUTPUT_REDACTION_FAILED
```

其余 `error_code` 只能取 R1B `M3G1WorkflowError.code` 的固定集合，不接受任意上游 code。失败仍输出一份
FAILED JSON；stderr 只写 `operation:error_code`（operation 未知写 `CLI:error_code`）。不得打印 traceback；`main()` 内捕获已知项目
异常并映射，未知异常统一 `CLI_INTERNAL_ERROR`/2，不输出原文本。测试可直接调用内部 `_run(argv)` 取得结果，
但生产 `main` 只返回 int。

### 6.1 count 与 identity 生命周期

CLI counts 直接复制 R1B 的**计划总数**，不是已完成 receipt 数；尚未派生的 history/reference 为 0。失败时
保留失败发生前最后一份 verified state 的 counts/stages，若 config/root 尚未验真则全部为 0、stages 为空。

| verified/返回态 | primary_candidate_key | release_id | manifest_sha256 |
|---|---|---|---|
| HISTORY 未完成 | `None` | `None` | `None` |
| HISTORY/REFERENCE 完成 | candidate key | `None` | `None` |
| 显式 PREPARE 返回态 | candidate key | prepared release ID | `None` |
| PUBLISH | candidate key | release ID | verified manifest hash |

普通 `status` 在仅做过 prepare、尚未 publish 时仍按磁盘证据返回 REFERENCE；PREPARE 是瞬时纯函数结果，
不能伪造成持久完成 marker。

### 6.2 输出敏感模式

在严格 schema 闭包之外再扫描规范 JSON bytes；至少拒绝下列大小写不敏感模式：

```text
(token|password|secret|api_key|apikey) 后跟可选空白和 ':'/'='
"Bearer "
[A-Za-z]:\\                         # Windows drive absolute path
/mnt/[A-Za-z]/                       # WSL mounted drive path
/home/
tushare.local.toml
```

不得用“任意长 hex”规则扫描，因为合法 SHA-256 正是 64 hex。scanner 只处理最终受控 bytes，不读取或比较本地
token；无网络的 status/prepare/publish 不得为扫描而加载敏感配置。

## 7. Tushare 错误分类器

R1C 提供私有 `_classify_tushare_error(exc) -> str`，只供 R1B/B2A executor：

- `TimeoutError`、连接中断/超时类和明确 socket/network errno → `NETWORK`；
- 稳定小写文本包含 `rate limit`、`too many requests`、`每分钟最多访问`、`访问频次` → `RATE_LIMIT`；
- HTTP 502/503/504 或 `temporarily unavailable` → `TRANSIENT_SERVER`；
- 其余 → `PERMANENT`。

分类可读异常链但绝不保存/输出文本；链循环和恶意 `__str__` 必须安全退化 PERMANENT。不得把所有
`OSError` 都当网络错误，不得按 token/账号内容分类。真实 R0 若发现 SDK 使用不同且稳定的限频形态，必须由
主 Agent 先修订本 allowlist，再实现，不能由 Agent 临时放宽。

## 8. 真实全量运行协议

真实运行的当前请求规模、分阶段授权点与内核能力证据见
[`M3_G1_R1C-B真实运行授权与资源清单.md`](M3_G1_R1C-B真实运行授权与资源清单.md)。该清单只拆分外部
额度决策点，不得缩短本节冻结的科学区间或端点集合。

### 8.1 执行顺序

1. `status` 保存脱敏摘要；
2. `index`，完成后新进程 `status`；
3. `history`，允许长运行和断点重启，完成后新进程 `status`；
4. `reference`，完成后新进程 `status`；
5. `prepare` 两次独立冷启动，要求 release ID、candidate key、counts 完全相同；
6. `publish` 仅当 `platform_supports_renameat2_noreplace()==true`；否则不调用并在报告明确外部门禁。

每次命令都在 WSL base。禁止并发运行两个写阶段；锁语义只由已验收 R1L `flock` 决定，持久
`.writer.lock` 文件存在本身不是 active，CLI 不探 PID、不删 lock。限频和 retries 只使用 C0 值。不得为
赶进度减少历史区间、证券并集、七端点或 30×20 对账。

### 8.2 长运行证据

报告只记录：阶段、request 总数/已完成数、history symbols、stable identity、质量汇总、开始/结束 UTC 和
稳定失败 code。不得复制 request 参数全集、raw 行、绝对路径、token 或 SDK异常。时间不进入任何 identity。

任一永久端点失败时停止，保留可恢复证据并形成任务书矛盾/权限阻塞报告；不得把空响应政策改成 ALLOW。
跨源 mismatch 必须保留完整本地 detail，但报告只写汇总。

## 9. 自动测试

至少覆盖：

1. 七命令的 connector 实例化/网络调用边界和严格停止点；
2. `run-all` 每个 stop-after、每阶段故障、断点重跑；
3. stdout 一行、严格 JSON、字段闭包、无路径/token/NaN，stderr 稳定；
4. `status INCOMPLETE` exit 0，其余错误码矩阵；
5. argparse 拒绝 token/path/rate/version 隐式覆盖和未知参数；
6. 分类器网络/限频/502/永久、恶意异常链、message 含 token/绝对路径；
7. connector 构造器若被前置失败触发即失败测试；
8. `publish` unsupported 不调用 publisher；supported 才调用；
9. 两次 prepare identity 稳定；
10. import 隔离和全量 pytest/Ruff/mypy。

## 10. 独立初验与真实复验

代码初验先用全新 Grok High 会话，新增未知参数注入、stdout partial-write、恶意异常 repr、config symlink 和
`run-all` 中段重启对抗。通过主验后才允许真实全量运行。

真实运行完成后再用另一全新会话，只读 journal/raw/prepare/release，重新运行 `status`、两次 `prepare` 和
凭据扫描；可新增一个不同 Tushare 最小只读请求验证当前权限，但不得重跑完整历史。发现问题返回原实现
会话修复/重跑，再独立复验，直到通过才进入主 Agent 终验。
