"""Generate a bounded, preregistered intraday mechanism battery without an LLM."""
import hashlib
import datetime as dt
import json
import tomllib
from pathlib import Path


FAMILIES = {
    'opening_range_breakout': ('10:30', '开盘区间突破：10:30已完成收盘突破09:30至10:00最高价且高于已知VWAP，14:50退出。'),
    'vwap_reclaim': ('13:30', '午后均价收复：13:25收盘低于此前VWAP、13:30收盘重新站上当日已知VWAP，14:50退出。'),
}


def generate(spec_path, root):
    raw = spec_path.read_bytes()
    spec = tomllib.loads(raw.decode('utf-8'))
    template_raw = Path(spec['template']).read_bytes()
    base = tomllib.loads(template_raw.decode('utf-8'))
    if spec['auto_trade'] is not False or base['auto_trade'] is not False:
        raise ValueError('Require auto_trade=false')
    if not set(spec['symbols']) <= {'518880.SH', '511010.SH'}:
        raise ValueError('Only verified T+0 ETF instruments supported in this battery')
    if not set(spec['families']) <= set(FAMILIES):
        raise ValueError('Unregistered mechanism')
    replay_raw = Path(__file__).with_name('intraday_afternoon.py').read_bytes()
    fingerprint = hashlib.sha256(raw+template_raw+Path(__file__).read_bytes()+replay_raw).hexdigest()
    folder = root / 'candidates' / fingerprint
    folder.mkdir(parents=True, exist_ok=True)
    # A changed implementation is a new experiment, never retroactive forward evidence.
    fingerprint_clock = folder / 'registered.json'
    if not fingerprint_clock.exists():
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
        first = max(dt.date.fromisoformat(spec['forward_start']), now.date()+dt.timedelta(days=1))
        with fingerprint_clock.open('x', encoding='utf-8') as stream:
            json.dump(dict(created_at=now.isoformat(), forward_start=str(first)), stream)
    registration = json.loads(fingerprint_clock.read_text(encoding='utf-8'))
    paths = []
    for symbol in spec['symbols']:
        for family in spec['families']:
            time, description = FAMILIES[family]
            cfg = {**base, 'symbol': symbol, 'signal_kind': family, 'signal_time': time,
                   'description': symbol+' '+description, 'forward_start': registration['forward_start'],
                   'execution_model': 'next_5m_worst'}
            text = '\n'.join(f'{key} = {json.dumps(value, ensure_ascii=False)}'
                             for key, value in cfg.items())+'\n'
            path = folder / f'{family}_{symbol}.toml'
            if path.exists():
                if path.read_text(encoding='utf-8') != text:
                    raise ValueError('Frozen candidate changed')
            else:
                with path.open('x', encoding='utf-8') as stream:
                    stream.write(text)
            paths.append(path)
    for name, data in [('search.toml', raw), ('template.toml', template_raw), ('replay.py', replay_raw)]:
        path = folder / name
        if not path.exists():
            path.write_bytes(data)
        elif path.read_bytes() != data:
            raise ValueError('Frozen search input changed')
    return paths
