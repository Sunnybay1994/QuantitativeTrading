# M1 2026-07-10 双 Route 真实 60 日行情 Coverage 主 Agent 审计记录

日期：2026-07-18  
性质：零网络、只读现状审计；不构成 M1、M1-X2-R1 或任何 Gate 通过

## 1. 审计命令

在 Windows Miniforge base、工作区 `F:\AI_Coding\QuantitativeTrading` 中分别运行：

```text
python -m quant.data.query_universe --universe SH_CONNECT \
  --as-of 2026-07-10 --source tushare --observations 60 --data-root data

python -m quant.data.query_universe --universe SZ_CONNECT \
  --as-of 2026-07-10 --source tushare --observations 60 --data-root data
```

未指定 `--output`，因此命令只读 clean Parquet 并打印 coverage JSON；两次均 exit 0。未联网、未读取
`data/legacy/`、未写 raw/clean/artifacts。

## 2. 结果

| Route | eligible | returned | missing | short | min/max | full-window symbols |
|---|---:|---:|---:|---:|---:|---:|
| SH_CONNECT | 644 | 2 | 642 | 2 | 0 / 1 | 0 |
| SZ_CONNECT | 644 | 2 | 642 | 2 | 0 / 1 | 0 |

两路由仅返回：

- `00005.HK`：1 个观测；
- `00700.HK`：1 个观测。

两者日期均为 2026-07-10；请求窗口为每证券 60 个观测。两路由 `is_full_window=false`，其余 642 个
eligible symbols 全部列入 canonical `missing_symbols`。

## 3. 结论与使用边界

- 当前数据明确不能满足路线图验收标准“某日全市场可交易股票的近 60 日行情”；缺口不是查询 SQL 能力问题，
  而是真实 clean 行情覆盖不足。
- M1-X2 audited 查询已能把缺口显式呈现；但其公共 `BarWindowCoverage` 手工构造仍存在跨字段严格校验缺陷，
  正等待 X2-R1 外部返工。因此本记录只证明这次由库查询生成的合法 coverage payload 与实际数据现状，不证明
  X2-R1 已主验通过。
- 后续真实数据恢复必须以 source/endpoint 权限、限频和 raw 不可变合同为边界；不得用当前名单、其他 source
  或常量因子静默补齐，也不得把 2 个单日样本表述成全市场覆盖。
