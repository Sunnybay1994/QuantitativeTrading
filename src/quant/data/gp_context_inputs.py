"""N3-compatible full-market inputs for bounded GP cross-section subtrees."""
from __future__ import annotations

import ast
import bisect
from collections import OrderedDict
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_inputs, read_factor_industry
from quant.factors.expressions import _WINDOW, required_history

KEYS = ['symbol', 'trade_date']


def sha256(path: Path) -> str:
    before = path.stat()
    with path.open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'GP context input changed while hashing: {path}')
    return value


def dump(path: Path, value: dict) -> None:
    """Atomic JSON replace with short retries for Windows destination locks."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (2 ** min(attempt, 4)))


def null_without_bar(expression: str) -> bool:
    """Prove a published terminal is null on padded non-bar rows; otherwise recompute.

    Published factors only save observed-bar rows. Financial carry, delay, constant
    branches and unrecognized intrinsic fields cannot be blindly reused on a grid.
    """
    bar_fields = {'open', 'high', 'low', 'close', 'adj_open', 'adj_high', 'adj_low',
                  'adj_close', 'volume', 'amount', 'adj_factor', 'turnover_rate',
                  'total_mv', 'circ_mv', 'pe_ttm', 'pb'}

    def visit(node):
        if isinstance(node, ast.Name):
            return node.id in bar_fields
        if isinstance(node, ast.UnaryOp):
            return visit(node.operand)
        if isinstance(node, ast.BinOp) and not isinstance(node.op, ast.Pow):
            return visit(node.left) or visit(node.right)
        if isinstance(node, ast.Compare):
            return visit(node.left) or any(visit(x) for x in node.comparators)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == 'delay':
                return False
            if name == 'where':
                return visit(node.args[0]) or (visit(node.args[1]) and visit(node.args[2]))
            if name in {'ts_corr', 'ts_cov'}:
                return visit(node.args[0]) or visit(node.args[1])
            if name in (_WINDOW - {'delay'}) | {'abs', 'log', 'exp', 'sign', 'sqrt', 'rank', 'scale', 'ind_neutralize'}:
                return visit(node.args[0])
        return False

    return visit(ast.parse(expression, mode='eval').body)


class FullMarketInputs:
    """Read a narrow yearly context, reuse safe published terminals, bound RAM."""

    def __init__(self, *, data_root: Path, refresh_config: Path, output: Path,
                 start: dt.date, end: dt.date, mapping: dict[str, str],
                 maximum_rows: int, memory_mb: int):
        self.root, self.output, self.start, self.end = data_root, output, start, end
        self.mapping, self.maximum_rows = mapping, maximum_rows
        self.maximum_bytes = memory_mb * 1024**2
        self.frames: OrderedDict[tuple, tuple[pl.DataFrame, pl.DataFrame]] = OrderedDict()
        self.sources_path = output/'source_manifest.json'
        self.sources = json.loads(self.sources_path.read_text(encoding='utf-8')) if self.sources_path.exists() else {}
        self.stamps = {}
        self.sessions = available_sessions(data_root, end)
        frozen = output/'refresh.toml'
        original = frozen.read_bytes() if frozen.exists() else refresh_config.read_bytes()
        if not frozen.exists():
            frozen.write_bytes(original)
        self.config = frozen
        # Global daily-refresh pointers may advance while a batch sleeps. Resume
        # the saved config and its actual source bytes, never the live pointer.
        self.track(frozen)
        # On resume, verify the bytes of every previously used source before any
        # projected subtree or fitness cache can be reused.
        for name in list(self.sources):
            self.track(Path(name))
        settings = tomllib.loads(original.decode('utf-8'))
        self.source_settings = settings
        self._base_sources(settings)
        self.metrics = {'safe_terminal_reads': 0, 'expanded_context_reads': 0,
                        'base_cache_hits': 0, 'largest_context_rows': 0}

    def track(self, path: Path) -> None:
        name = str(path.resolve())
        if not path.exists():
            if name in self.sources and self.sources[name] is not None:
                raise ValueError(f'Frozen GP context source disappeared: {path}')
            self.sources[name], self.stamps[name] = None, None
            dump(self.sources_path, self.sources)
            return
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns)
        if name in self.stamps:
            if self.stamps[name] != stamp:
                raise ValueError(f'Frozen GP context source changed: {path}')
            return
        value = sha256(path)
        if name in self.sources and self.sources[name] != value:
            raise ValueError(f'Frozen GP context source checksum changed: {path}')
        self.sources[name], self.stamps[name] = value, stamp
        dump(self.sources_path, self.sources)

    def _base_sources(self, settings: dict) -> None:
        # Resolve only the immutable historical snapshot tables used in this
        # training window, not the unrelated active raw collector's directories.
        roots = [self.root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/'bar_1d/asset=stock',
                 self.root/'clean/tushare_daily_basic/snapshots'/settings['daily_basic_snapshot']]
        lookback = max((required_history(x) for x in self.mapping.values()), default=0) + 300
        low = self.sessions[max(0, bisect.bisect_left(self.sessions, self.start) - lookback)]
        base_low = low
        from quant.factors.return_seasonality import SEASONALITY_NAMES
        if any(any(n.id in SEASONALITY_NAMES for n in ast.walk(ast.parse(expr)) if isinstance(n,ast.Name))
               for expr in self.mapping.values()):
            from quant.data.factor_seasonality_inputs import seasonality_price_start
            low = seasonality_price_start(low)
        from quant.factors.turnover_reference import NAMES as TURNOVER_NAMES, CONTROLS as TURNOVER_CONTROLS
        if any(any(n.id in (*TURNOVER_NAMES, *TURNOVER_CONTROLS) for n in ast.walk(ast.parse(expr)) if isinstance(n, ast.Name))
                for expr in self.mapping.values()):
            from quant.data.factor_turnover_reference_inputs import turnover_reference_start
            low = min(low, turnover_reference_start(base_low))
        from quant.factors.industry_information import SIGNALS, CONTROL
        if any(any(n.id in (*SIGNALS, CONTROL) for n in ast.walk(ast.parse(expr)) if isinstance(n, ast.Name))
                for expr in self.mapping.values()):
            year, month = divmod(base_low.year*12+base_low.month-1-6,12)
            low = min(low, dt.date(year,month+1,1))
        self.low = low
        for root in roots:
            for year in range(low.year, self.end.year + 1):
                for path in sorted((root/f'year={year}').glob('*.parquet')):
                    self.track(path)
        for path in sorted((self.root/'clean/tushare_incremental').glob('date=*')):
            if str(low) <= path.name[5:] <= str(self.end):
                for name in ('bar_1d.parquet', 'daily_basic.parquet', 'adjust_factor.parquet'):
                    if (path/name).exists():
                        self.track(path/name)
        self.industry = None
        for path in sorted((self.root/'clean/tushare_industry').glob('*/summary.json'), reverse=True):
            if json.loads(path.read_text(encoding='utf-8')).get('with_current'):
                self.industry = path
                self.track(path)
                self.track(path.parent/'intervals.parquet')
                break
        for path in (self.root/'clean/trade_calendar').glob('market=*/data.parquet'):
            self.track(path)
        if settings.get('financial_snapshot'):
            for path in (self.root/'clean/tushare_financials'/settings['financial_snapshot']).glob('*.parquet'):
                self.track(path)
        self.base_paths = self._base_paths()
        inventory = self.output/'base_paths.json'
        if inventory.exists() and json.loads(inventory.read_text()) != self.base_paths:
            raise ValueError('Frozen GP base source inventory changed')
        if not inventory.exists():
            dump(inventory, self.base_paths)

    def _base_paths(self) -> list[str]:
        settings = self.source_settings
        roots = [self.root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/'bar_1d/asset=stock',
                 self.root/'clean/tushare_daily_basic/snapshots'/settings['daily_basic_snapshot']]
        paths = [p for root in roots for year in range(self.low.year, self.end.year + 1)
                 for p in (root/f'year={year}').glob('*.parquet')]
        paths += [p/name for p in (self.root/'clean/tushare_incremental').glob('date=*')
                  if str(self.low) <= p.name[5:] <= str(self.end)
                  for name in ('bar_1d.parquet', 'daily_basic.parquet', 'adjust_factor.parquet')
                  if (p/name).exists()]
        return sorted(str(p.resolve()) for p in paths)

    def _aux_sources(self, expression: str, bars: pl.DataFrame) -> None:
        from quant.research.factor_financials import financial_input_names
        from quant.research.factor_market import market_input_names
        from quant.data.forecast_numeric import forecast_numeric_input_names
        settings = self.source_settings
        from quant.factors.industry_information import SIGNALS, CONTROL
        if any(n.id in (*SIGNALS,CONTROL) for n in ast.walk(ast.parse(expression)) if isinstance(n,ast.Name)):
            definition = Path('configs/research/industry_information_family_v1.toml')
            self.track(definition)
            registered = tomllib.loads(definition.read_text(encoding='utf-8'))
            folder = self.root/'clean/tushare_industry'/registered['initial_industry_snapshot']
            self.track(folder/'intervals.parquet')
            self.track(folder/'summary.json')
        if 'pit_annual_fscore' in financial_input_names((expression,)):
            folder = self.root/'clean/cninfo_share_changes'/settings['financial_share_changes_snapshot']
            for name in ('events.parquet', 'request_coverage.parquet'):
                self.track(folder/name)
            if settings.get('financial_share_change_notices'):
                self.track(Path(settings['financial_share_change_notices']))
        if market_input_names((expression,)):
            self.track(self.root/'clean/factor_benchmark'/settings['factor_benchmark_snapshot']/'bars.parquet')
        from quant.research.factor_monthly import monthly_input_names
        from quant.factors.price_delay import PRICE_DELAY_NAMES
        if set(monthly_input_names((expression,))) & set(PRICE_DELAY_NAMES):
            folder = self.root/'clean/index_benchmarks'/settings['price_delay_index_version']
            for name in ('data.parquet', 'summary.json'):
                self.track(folder/name)
        if forecast_numeric_input_names((expression,)):
            path = Path(settings['forecast_numeric_corpus'])
            self.track(path if path.is_absolute() else self.root/path)
        # Minute parquets are rewritten by collectors and stay out of the N2
        # freeze inventory. A minute writer must not fail the source checksum.
        from quant.factors.statement_event_reaction import NAMES as STATEMENT_NAMES
        from quant.factors.turnover_reference import NAMES as TURNOVER_NAMES, CONTROLS as TURNOVER_CONTROLS
        if any(n.id in (*TURNOVER_NAMES, *TURNOVER_CONTROLS) for n in ast.walk(ast.parse(expression)) if isinstance(n, ast.Name)):
            self.track(Path('configs/research/turnover_reference_price_family_v1.toml'))
        if any(n.id in STATEMENT_NAMES for n in ast.walk(ast.parse(expression)) if isinstance(n, ast.Name)):
            definition = Path(settings['statement_event_definition'])
            self.track(definition)
            spec = tomllib.loads(definition.read_text(encoding='utf-8'))
            self.track(Path(spec['legacy_quarantine']))
            self.track(self.root/'clean/tushare_financials'/settings['financial_snapshot']/'income.parquet')
            folder = self.root/'clean/index_benchmarks'/settings['statement_event_index_version']
            for name in ('data.parquet', 'summary.json'):
                self.track(folder/name)

    def verify_sources(self) -> None:
        if self._base_paths() != self.base_paths:
            raise ValueError('Frozen GP base source inventory changed')
        for name in self.sources:
            self.track(Path(name))
        if self.industry:
            current = next((p for p in sorted((self.root/'clean/tushare_industry').glob('*/summary.json'), reverse=True)
                            if json.loads(p.read_text(encoding='utf-8')).get('with_current')), None)
            if current != self.industry:
                raise ValueError('Full-context PIT industry snapshot changed')

    def _base(self, start: dt.date, end: dt.date) -> tuple[pl.DataFrame, pl.DataFrame]:
        self.verify_sources()
        key = (start, end)
        if key in self.frames:
            self.metrics['base_cache_hits'] += 1
            self.frames.move_to_end(key)
            return self.frames[key]
        panel, bars = read_factor_inputs(self.root, self.config, start, end, self.sessions)
        if panel.height > self.maximum_rows:
            raise ValueError('GP full-context row budget exceeded; trial not approximated')
        self.metrics['largest_context_rows'] = max(self.metrics['largest_context_rows'], panel.height)
        size = panel.estimated_size() + bars.estimated_size()
        if size <= self.maximum_bytes:
            while self.frames and sum(x.estimated_size() + y.estimated_size() for x, y in self.frames.values()) + size > self.maximum_bytes:
                self.frames.popitem(last=False)
            self.frames[key] = (panel, bars)
        return panel, bars

    def read(self, expression: str, expanded: str, low: dt.date, high: dt.date) -> tuple[pl.DataFrame, str, str]:
        names = {n.id for n in ast.walk(ast.parse(expression, mode='eval')) if isinstance(n, ast.Name)}
        terminals = sorted(names & self.mapping.keys())
        safe = bool(terminals) and all(null_without_bar(self.mapping[name]) for name in terminals)
        history = required_history(expression if safe else expanded)
        start = self.sessions[max(0, bisect.bisect_left(self.sessions, low) - history)]
        panel, bars = self._base(start, high)
        if safe:
            if any(name.startswith('industry_') for name in names):
                panel = read_factor_industry(self.root, panel)
            fields = sorted(names & set(panel.columns) - set(KEYS))
            panel = panel.select(*KEYS, *fields)
            for name in terminals:
                definition = self.root/'factors'/name[3:]/'definition.json'
                self.track(definition)
                saved = json.loads(definition.read_text(encoding='utf-8'))
                if ast.dump(ast.parse(saved['expr'], mode='eval')) != ast.dump(ast.parse(self.mapping[name], mode='eval')):
                    raise ValueError(f'Published full-context terminal definition changed: {name}')
                paths = [self.root/'factors'/name[3:]/f'year={year}'/'data.parquet'
                         for year in range(start.year, high.year + 1)]
                for path in paths:
                    self.track(path)
                paths = [p for p in paths if p.exists()]
                if paths:
                    values = pl.scan_parquet(paths).filter(pl.col('trade_date').is_between(start, high)).select(
                        pl.col('ts_code').alias('symbol'), 'trade_date', pl.col('value').cast(pl.Float64).alias(name)).collect()
                    panel = panel.join(values, on=KEYS, how='left', validate='1:1')
                else:
                    panel = panel.with_columns(pl.lit(None, dtype=pl.Float64).alias(name))
                self.metrics['safe_terminal_reads'] += 1
            return panel, expression, 'published_full_market_terminals_with_null_support_proof'
        from quant.factors.compute import attach_expression_inputs
        self._aux_sources(expanded, bars)
        panel = attach_expression_inputs(panel, bars, expressions=(expanded,), data_root=self.root,
            refresh_config=self.config, read_start=start, read_end=high, sessions=self.sessions)
        self.verify_sources()
        self.metrics['expanded_context_reads'] += 1
        return panel, expanded, 'expanded_N3_inputs_for_non_bar_null_terminals'
