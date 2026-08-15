# Cursor CLI 接入与探测记录

日期：2026-07-14  
状态：Windows Agent 已认证；2026-08-15 至 2026-08-20（含）按用户全局指示统一使用
`cursor-grok-4.6-high`，到期未续期则恢复暂停外部会话；WSL Agent 仍不可执行

## 1. 目的与边界

本记录只说明 Cursor CLI 能否作为项目四段式流程中的“实现 Agent”。主 Agent 仍负责任务书、独立初验和
最终验收。Cursor 的登录、API key、模型、MCP、`--force`/sandbox 和提示词模板必须由用户明确配置；不得
把密钥写入仓库、命令回显、报告或 artifact。

## 2. 实测结果

### Windows

- `cursor`：`3.11.13`，包含 `agent` 子命令；普通 CLI 主要用于打开 IDE。
- 独立 `cursor-agent`：`2026.02.27-e7d2ef6`。
- `cursor-agent --help` 确认支持 headless `--print`、`--output-format`、`--model`、`--workspace`、
  `--worktree`、`--trust`、plan/ask 模式和 MCP。
- `cursor-agent status` 确认当前 Windows CLI 已登录；本记录不保存或展示账户邮箱、认证 token 或其他身份信息。
- `cursor-agent models` 曾确认账号可用模型包含 `cursor-grok-4.5-high`，显示名为 `Cursor Grok 4.5`，另有
  `low`、`medium`、`high` 及对应 `fast` 变体。本项目后续若指定“Cursor Grok 4.5”，默认使用
  `cursor-grok-4.5-high`，除非任务书或用户另有说明。自 2026-08-11 起，用户已明确要求后续新会话统一
  使用 `--model auto`；2026-08-15 用户又临时授权本项目所有 session 在 2026-08-20（Asia/Shanghai，含）
  前统一改用 `--model cursor-grok-4.6-high`，该时间窗内以临时授权为准，不声称其他底层模型。
- 只读 smoke test 已用 `cursor-grok-4.5-high` 成功读取根 `pyproject.toml`，准确返回
  `requires-python=\">=3.10\"` 与 `pytest.ini_options.testpaths=[\"tests\"]`，退出码为 0，并返回约定标记。
  测试使用 `ask` 模式，未修改文件、未运行项目 Python 工具、未联网。
- 该次成功请求的 JSON envelope 给出请求级 usage：`inputTokens=33309`、`outputTokens=230`、
  `cacheReadTokens=16768`、`cacheWriteTokens=0`。这些数字仅代表单次请求，不等于账户计费周期累计用量。
- Windows→WSL 桥接 smoke test 证明普通 Agent 模式可以实际调用 `wsl.exe`，并从 WSL Miniforge `base`
  返回 `/home/mabw/miniforge3/bin/python` 与 `sys.platform=linux`，退出码 0。`ask` 模式会拒绝 shell，因此
  需要真实执行测试的实现/初验不能使用 `ask`/`plan`。

### WSL

- `/home/mabw/.local/bin/cursor-agent` 存在，版本目录内 Node 被识别为 Linux x86-64 ELF；WSL 也是 x86-64。
- 实际执行仍返回 `Exec format error`，因此当前 WSL 安装不可用，不能把“路径存在”解释为 Agent 可运行。
- WSL 中的 `cursor` 命令会桥接 `/mnt/d/Program Files/cursor/...` 的 Windows IDE CLI，不等于可用的 Linux
  headless Agent。

### 账户 usage 能力边界

- 当前版本的 `cursor-agent status` 只报告认证状态，`cursor-agent about` 只报告 CLI、模型、系统和账户基本
  信息；两者均不提供计费周期、套餐额度、累计已用量、剩余额度或重置日期。
- `--output-format json` 的成功结果含本次请求 token usage，可用于逐任务审计，但不能据此推断账户累计 usage。
- Cursor 官方 dashboard 的 usage 页需要独立 Web 登录；CLI 登录态不会自动共享给浏览器。本次可控浏览器没有
  已登录 Cursor 会话，因此未取得账户累计 usage，也未尝试读取或复制 CLI 认证状态来绕过登录。
- 让 Agent 自行查询账户累计 usage 的只读请求长时间无结果，已主动终止；不得把超时或缺失输出写成额度为 0。

## 3. 推荐接入方式

短期使用 Windows `cursor-agent`，workspace 指向本项目 Windows 路径；任务书必须明确：任何 Python、pytest、
Ruff、mypy 和项目脚本都由它通过 WSL Miniforge base 执行，禁止 Windows Python。若任务需要隔离 worktree，
须先修复当前空 `.git` 元数据；现工作副本的 `.git` 目录为空，不能使用基于 Git 的 Cursor worktree。

推荐的只读调用骨架（提示词内容通过 PowerShell 变量传入，避免复杂转义）：

```powershell
& "$HOME\AppData\Local\cursor-agent\cursor-agent.ps1" `
  --print --output-format json --mode ask `
  --model cursor-grok-4.6-high --trust `
  --workspace 'G:\BaiduSyncdisk\wsl\Cursor\quant' `
  $prompt
```

需要写实现或实际运行 WSL 检查时使用普通 Agent 模式：

```powershell
& "$HOME\AppData\Local\cursor-agent\cursor-agent.ps1" `
  --print --output-format json --force `
  --model cursor-grok-4.6-high --trust `
  --workspace 'G:\BaiduSyncdisk\wsl\Cursor\quant' `
  $prompt
```

初始提示词应让 Agent 读取仓库内任务书，不要把含大量命令行 flag 的完整任务书文本直接拼进 CLI 参数；本次
探测中，提示词内的 `-n` 曾被 Windows wrapper 误解析为 Agent 选项。实现提示必须再次声明“Windows Agent、
WSL 项目运行时”的边界。独立初验使用全新会话；若需要运行测试和写固定验收报告也使用普通 Agent 模式，
但明确禁止改生产代码与实现者测试。

`--force` 只允许在任务书已冻结文件范围、禁止项和外部副作用的情况下使用；不得因此扩大删除、联网、凭据、
订单或账户权限。Cursor 输出只视为实现者证据，不能代替未参与实现的外部 Agent 独立初验与主 Agent 最终验收。

## 4. 上下文节制与交付回传

Cursor 的完整搜索、安装和测试日志不应回填到主 Agent 对话。任务提示应要求实现 Agent 与独立初验 Agent
均按下列固定结构返回：

1. 任务与结论（通过、待返工或受外部条件阻塞）；
2. 修改/审查的文件清单；
3. 执行过的命令及其退出码；
4. 仅保留失败摘要、关键断言和产物路径，不粘贴完整日志；
5. 已知风险、未验证项和下一步。

每个子包结束后再启动新的外部会话执行下一角色，不能以续聊代替独立初验。主 Agent 在吸收交付报告、写入
任务/验收记录后，可使用 `/compact` 压缩当前 Codex 任务上下文；压缩不会改变本项目的职责隔离或验收证据要求。
