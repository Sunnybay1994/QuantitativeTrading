1. 保留 `HkCorporateActionSourceAdapter.verify_retained(...) -> VerifiedHkCorporateActionProjection` 签名和
   adapter-facing factory，避免让 fixture/未来真实 adapter 自行实现私有构造器；但 factory 返回值标记为
   `adapter_parsed`，不能直接传给 selector/result verifier。
2. `verify_hk_corporate_action_source` fresh 重验 capability/query/bundle/candidates/projection digest 后，创建新的
   `source_verified` projection，并附加不可序列化、repr/compare 排除的 content-bound attestation。
3. attestation 使用模块进程内随机密钥与 HMAC-SHA256（或等价不可由公开摘要单独重算的窄机制），payload 精确
   绑定 source、adapter version、query identity、bundle identity、candidate table digest 与 projection digest。
   selector、result verifier 每次 fresh 重算 payload/HMAC 并 constant-time 比对；content 任一变化、旧 token
   复用、factory-only projection、复制后重哈希均 fail closed。
4. 进程内密钥不导出、不进入 dataclass repr/equality、日志、artifact 或文档。不得提供“签任意 projection”的
   公共 helper；HMAC 签发只发生在 source wrapper 成功路径。
5. 这是进程内 capability 防替换，不是外部数据源数字签名、跨进程持久证书或 WORM。projection 不序列化；
   进程重启必须再次调用 source wrapper 对 retained bytes fresh verification，报告必须如实披露。
6. R2 fresh digest 与异常链修复保持；不改变 schema/revision/as_of/selection/错误码，不引入网络或真实 adapter。

### R3 必测与通过条件

- R2 独立复验的 raw→bundle→candidate→projection 全链合法重哈希 + 旧 seal/token 复用必须失败；
- factory-only projection 直接 selector/result verifier 失败；经 source wrapper 返回的 exact projection 正常通过；
- 旧 attestation 分别复用到改 content、metadata、bundle source issue、candidate row、projection digest 的对象均失败；
- whole-result、future withdrawal、tombstone、异常矩阵与 R2 fresh digest 回归保持绿色；
- monkeypatch HMAC/adapter hostile 异常仍稳定脱敏、cause/context 为空且 token/key 不泄露；
- Windows 与 WSL base `/mnt/f` 定向 pytest/Ruff/mypy 通过，DrvFS 非 ext4。全新独立复验 PASS 后才可关闭 P0。
