# M4 P8 R3：独立 Append Anchor Journal 交付报告

日期：2026-08-09  
状态：R3 返工实现与自测完成；`WAITING_FOR_SOAK_EVIDENCE`；等待全新独立复验

## 返工结论

R3 在 R2 evidence root 之外增加显式、独立、绝对 `anchor_root`，用连续 append-only completion chain 绑定
首次实际落盘的 receipt/facts。它关闭了 R2 独立复验发现的“换入另一份语义完全合法 closure 并全链重哈希”
旁路，以及 verified 后磁盘漂移仍使用旧 capability 判定的 TOCTOU。

## 双根与公共合同

- `build_soak_run` 新增 `anchor_root`；manifest 新增不可逆 `anchor_root_identity` 并纳入 `run_id`。
- evidence root 与 anchor root 必须不同、互不为祖先/后代，且任何已存在祖先不得是 symlink 或 Windows junction。
- append、verify、decision 均显式接收同一双根；绝对路径原文不进入 manifest、receipt、anchor 或公开错误。
- `verify_soak_evidence` 返回的 development/formal capability 增加 `terminal_anchor_id`，evidence identity 同时绑定它。
- `decide_soak_gate` 在计算状态前 fresh 调用双根 verifier，并要求 fresh capability 与调用方传入值 exact equal。

## `SoakAppendAnchor` 与完成状态机

新增安全导出的 versioned `SoakAppendAnchor`，字段绑定：run、十进制 sequence、session/fault kind 与 key、
evidence root identity、previous anchor id、receipt id、facts digest tuple、私有 UTC `anchored_at` 和 anchor id。

anchor journal 精确目录是 `<anchor_root>/<run_id>/anchors/<十位sequence>.json`：

1. writer 先 exclusive/no-clobber 写完 R2 receipt/facts exact set，并从磁盘重新严格自验；
2. 再读取完整 anchor chain，验证连续 sequence、唯一 key、严格 predecessor、递增 UTC 和 canonical bytes；
3. 最后 exclusive-create 下一 sequence，作为唯一 completion marker；
4. 同 key、同 receipt/facts 重试直接命中原 anchor，不增加 sequence；同 key 异 facts/receipt 稳定冲突；
5. anchor 前崩溃留下的 exact evidence 可在以后补锚，异 bytes 不能重签；formal 补锚自身仍使用当前私有 UTC；
6. 两个不同 next entry 并发竞争同一 sequence 时只允许一个创建成功，失败者保留未锚 exact evidence并返回
   `SOAK_APPEND_CONFLICT`；随后重读 terminal 的 exact retry 接续下一 sequence，不覆盖、跳号或分叉。

verifier 对 evidence 与 anchor 做双向 exact 对应：每个观察 session/fault 必须恰有一条 anchor，且每条 anchor
必须指向现存 receipt/facts；terminal anchor 进入 capability 与 evidence identity。

## 新增对抗证据

- 使用两套公开 P5/P7 builder 生成的不同、均语义合法 closure，整体替换原 session 并重算所有 identity；
  anchor 不变时 fresh verifier 拒绝。
- public writer 不能给已有 key 重签，也不能用 `_write_once` 覆盖旧 anchor；模拟同机直接重写 evidence+anchor
  后，旧 capability 在 decision fresh-equal 边界拒绝。
- anchor 删除、增加、交换、跳号、重复 key、错误 predecessor、receipt、facts digest、复制到另一 root、symlink
  全部 fail closed。
- evidence 完整但 anchor 缺失的 crash 恢复只接受 exact bytes；相同重试保持单 anchor，异 closure 冲突。
- verify 后新增合法 anchor、删除 evidence、删除 anchor 三类磁盘漂移均在 decision 状态计算前拒绝。
- 强制两个 fault writer 同时读取空 terminal 并竞争 sequence 1：只有一个成功；失败者 exact retry 后得到严格
  `1 -> 2` 链，fresh verify 通过且无分叉。
- R2 可信时钟、双平台 root、strict retained codec、development never-PASS 等既有反例保持绿色。

## 验证结果

Windows 原生 Miniforge：

- P8 R3 定向：`40 passed, 1 skipped`；skip 为 Windows 主机未授予 symlink 创建，WSL 对应反例实际通过；
- P5-P8 合流：`510 passed, 6 skipped`；
- Ruff：`All checks passed!`；
- mypy：`Success: no issues found in 2 source files`。

WSL Miniforge base、`/mnt/f`：

- P5-P8 同范围合流：`516 passed`，包含 anchor symlink 反例；
- Ruff 与 mypy 均通过；
- `findmnt` 确认 `/mnt/f` 为 `drvfs`。该证据只证明 WSL base + DrvFS 开发兼容，不是 ext4/Linux 正式 Gate。

## 信任边界与未完成

- 本地 anchor journal 的信任边界是可信本机、exclusive append 与首次 bytes 保留；它不是数字签名、WORM、
  硬件可信时间或抵抗本机管理员的证明。具备任意文件改写权限者若不持有旧 capability并同时重造双根、manifest、
  anchor 与业务 wire，仍超出 R3 防护范围；更强威胁模型需外部签名或远端不可变审计。
- 本轮没有启动/注册正式 28 日 soak，没有访问网络/broker，没有写正式 artifacts/journal，也没有 add/commit。
- development 证据仍永不 PASS；真实四周、正式 runner、ext4/Linux Gate 均保持开放。只有全新独立复验 PASS
  后才可冻结和注册正式 runner。

