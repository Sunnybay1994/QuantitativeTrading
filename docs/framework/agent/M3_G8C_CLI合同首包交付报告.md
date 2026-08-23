# M3-G8C CLI 合同首包交付报告

## 交付

`quant.research.run_m3` 已补齐八个用户命令的严格 argparse 合同与 SSOT 停止点，
并新增 `CommandFailure`/`CommandSummary` 作为后续 handlers 的薄编排边界。summary 会
稳定排序所有失败，以最小非零分类作为进程退出码，并对输出数据递归执行
secret/绝对路径/非有限数门禁。

现有 formal `experiment-identity` 的解析参数、`execute=` 测试注入、成功与失败 JSON 形态
保持兼容。新命令在业务 dispatcher 未接入时稳定失败，不会写入或声称任何
研究与验收产物。

## 验证与边界

定向测试覆盖八命令参数/停止点、G1/snapshot XOR、fold/horizon 类型、code 2
执行前停止、多失败排序与最小退出码、canonical 单行 JSON、嵌套敏感值和异常脱敏，
以及旧 `experiment-identity` 回归。

- Windows Miniforge：定向 Ruff 通过，mypy `Success: no issues found in 2 source files`，
  pytest `24 passed`。
- WSL Miniforge base：对应 Ruff 通过，mypy `Success: no issues found in 2 source files`，
  pytest `24 passed`。

本报告只证明 G8C CLI 开发合同；formal handlers、
tracking、冷启动比较和 acceptance Gate 仍等待后续分包与真实证据。

独立初验返工已关闭 public exception code 注入、`//...` 路径遗漏及 dispatcher stdout
泄漏：public 异常固定为 `M3_COMMAND_FAILED/5`，不可信打印被捕获丢弃，四类绝对路径均
fail closed。legacy `experiment-identity` 的既有稳定 code 兼容保持不变。
