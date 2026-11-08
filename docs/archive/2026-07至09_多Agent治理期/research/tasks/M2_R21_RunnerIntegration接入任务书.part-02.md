以上均由原Worker 3恢复同一原实现subagent；禁止第二实现链。实现唯一可写：
`tests/unit/test_classic_eleventh_batch.py`及`docs/research/deliveries/M2_R21_SinglePassTrace交付报告.md`。
production、公共rank、配置、taskbook、roadmap及review在实现阶段只读。若反例证明必须改production，
先STOP提交最小反例申请扩围，不自行修公式。经理本轮仅追加本文并提交本文及原review。

### 9.2 fixture-only 定向复验

统筹同时批准本轮定向复验，不要求先再走一次静态交付。沿用§8的解释器、三个产品命令顺序、
单进程和线程上限；不得变更测试范围、安装依赖或运行经济入口。新证据根唯一为source内
`artifacts/agent_runs/m2-r21-single-pass-trace-rework1/`，旧根及缓存全部保留，不清理或覆盖。
每次尝试在新根内用独立未占用子目录，pytest basetemp及mypy cache均指向该次目录内；
pytest仍禁cacheprovider、Ruff仍--no-cache，PYTHONDONTWRITEBYTECODE=1。

在产品阶段前保存实际argv、cwd、解释器身份、生产/测试bytes与SHA，环境仅记录白名单
POLARS_MAX_THREADS、OMP_NUM_THREADS、PYTHONDONTWRITEBYTECODE、PYTHONPATH。
PYTHONPATH明确指向当前source/src；只做本模块冷导入，保存实际module.__file__，验证它解析到
当前source的冻结生产文件，不能仅凭环境声明推断。不得输出完整环境、凭据或加载真实数据。
导入身份不符即停止产品阶段，不能把main的结果计入本轮。

各阶段真实stdout、stderr、原生exit分别在该次目录新建留存；未运行阶段标UNRUN。
结果引用实际代码身份与attempt，失败不覆盖；修测试后需新的attempt。新运行不是旧证据恢复，
delivery必须把历史不可核验与新可核验结果分开。证据采集采用最小原生命令方式，不新建通用carrier框架。
本节不授权真实data、网络、ETF、receipt、labels、evaluate、publish、trial、PAPER或LIVE。

通过条件：两项P1及既冻反例的测试闭合，§8三项产品验证有独立可读取的原生证据及worktree导入身份；
同一原独立审查上下文复验，只写原review追加历史。通过上限仅Windows development validation；
未获统筹合流，不合并或退休source，完整R21接入及经济有效性继续未完成。

## 10. SinglePassTrace REWORK2 最小验收修正

2026-09-08原review追加REWORK1结论为REVIEW_FAIL / P0=0 / P1=2 / P2=1；
review为12224 bytes，SHA256=`ea004bcccd02d1916883f745161278673f872b6cf2bcc8ce98651a1ff5a3d3f0`。
原数学正零、异常及乱序反例已闭合；新证据根原生28 passed、Ruff及production mypy exit0有效，
但不替代缺失的产品前导入闸门。统筹批准本节一次最小返工，不改变生产公式或经济合同。

### 10.1 原链最小修改

- 原Worker 3恢复同一实现subagent，仅写原test与delivery；production、rank、config、taskbook、
  roadmap、review全部只读，不创建第二实现链。
- 普通unit的`test_runtime_import_identity_is_current_worktree`移除无条件Windows解释器路径断言，
  保留平台中性的当前source模块定位验证；不得用skip隐藏Linux不兼容，不改其他数学测试。
- delivery恢复提交`085e04488ba1d25bfdb1e3ef497efa148b9e8511`中的历史原文，随后仅追加更正及
  REWORK1/REWORK2真实证据。旧声明明确标为不可独立核验，但不删除或改写；禁止补造历史日志。
- 本轮根因：运行环境准入误放入可移植unit；pytest内断言不能追认产品前未执行的冷导入；
  历史更正采用替换而非追加。通过条件分别是普通unit无Windows绑定、独立前置真实身份留存、
  原文可逐字与历史commit比较且追加纠正不混淆新旧结论。

### 10.2 新证据与窄验证顺序

只使用source内新no-clobber根`artifacts/agent_runs/m2-r21-single-pass-trace-rework2/`，
保留所有旧根；任何阶段失败即STOP，不覆盖或盲重跑。沿用§9.2解释器、source cwd/PYTHONPATH、
单进程、线程上限及环境白名单，禁止输出完整环境。先保存输入bytes/SHA及实际argv/cwd。

1. 独立`D:\Miniforge3\python.exe`子进程只冷导入`quant.factors.classic_eleventh_batch`，
   保存实际`sys.executable`、`module.__file__`及该文件bytes/SHA，逐字核当前source生产身份
   `26009 / 3c28d5a6dbec36b9bbde06ab86f0d2a4deeaefd8798a03c10e117bc9f98c528d`；
   路径及解释器必须为本source与冻结Windows解释器，真实stdout/stderr/native exit独立留存。
   不读取真实data，不调用factor计算；身份不符则后两阶段零调用。
2. `D:\Miniforge3\python.exe -m pytest -q tests/unit/test_classic_eleventh_batch.py::test_runtime_import_identity_is_current_worktree -p no:cacheprovider --basetemp=artifacts/agent_runs/m2-r21-single-pass-trace-rework2/pytest`
3. `D:\Miniforge3\python.exe -m ruff check --no-cache tests/unit/test_classic_eleventh_batch.py`

每阶段独立原生stdout/stderr/exit，不新建通用carrier。只复用REWORK1中未变数学测试及production
mypy证据；须以diff证明相应代码/测试未改，不能声称新测试文件整体SHA未变或本轮全量重跑。
不授权production修改、full suite、网络、真实数据、ETF、labels/evaluate/publish/trial或交易。
完成后原实现者退出，由原reviewer仅追加原review复验，再申请提交/合流；本授权不含stage/commit。
