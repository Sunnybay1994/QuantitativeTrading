"""C1 operational limits; frozen experiment definitions and thresholds stay intact."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib


FIELDS=('id','expr','family','direction','source_ref')


def definition_hash(row):
    return hashlib.sha256(json.dumps({k:row[k] for k in FIELDS},sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()


def apply(settings, config=None):
    path=config or settings.get('compute_allocation_config')
    if not path:
        return settings
    policy=tomllib.loads(Path(path).read_text(encoding='utf-8'))
    if policy['auto_trade'] is not False or policy['gp_weekday']!=5 or policy['maximum_gp_batches_per_week']!=1:
        raise ValueError('Require C1 manual-only Saturday weekly limit')
    return {**settings,'compute_allocation_config':str(path),'compute_allocation':policy}


def allowed(row,settings):
    policy=settings.get('compute_allocation')
    if not policy:
        return True
    frozen=policy.get('ngp_backlog',{}).get(row['id'])
    if frozen:
        if definition_hash(row)!=frozen:
            raise ValueError(f"Frozen C1 backlog definition changed: {row['id']}")
        return True
    return not row['id'].startswith('ngp_') and row['id'] in policy['registered_candidates']


def require_allowed(definitions,settings):
    blocked=[d.id for d in definitions if not allowed({k:getattr(d,k) for k in FIELDS},settings)]
    if blocked:
        raise ValueError('C1 unregistered candidates in frozen battery: '+', '.join(blocked))


def may_enqueue(row,settings):
    if not allowed(row,settings):
        return False
    if settings.get('compute_allocation') and row['id'].startswith('ngp_'):
        completed=Path(settings['queue'])/'processing'/'completed'
        for path in completed.glob('*_'+row['id']+'.toml'):
            previous=tomllib.loads(path.read_text(encoding='utf-8'))
            if definition_hash(previous)==definition_hash(row):
                return False
    return True


def gp_permission(settings,output,*,claim=False):
    policy=settings.get('compute_allocation')
    if not policy:
        return {'allowed':True}
    # Resuming the same search is not another batch; population/RNG remain frozen.
    if (output/'search_checkpoint.json').exists():
        return {'allowed':True,'resume_existing':True}
    day=dt.date.fromisoformat(settings.get('scheduler_day',dt.date.today().isoformat()))
    if day.weekday()!=policy['gp_weekday']:
        return {'allowed':False,'reason':'C1 GP starts only on Saturday'}
    week=day-dt.timedelta(days=day.weekday())
    path=Path(settings['output_root'])/'gp_weekly'/f'{week}.json'
    identity=str(output.resolve())
    if path.exists():
        receipt=json.loads(path.read_text(encoding='utf-8'))
        return {'allowed':receipt['output']==identity,'reason':'C1 one batch per week',
            'weekly_receipt':str(path)}
    if claim:
        path.parent.mkdir(parents=True,exist_ok=True)
        try:
            with path.open('x',encoding='utf-8') as stream:
                json.dump({'output':identity,'week':str(week),'claimed_at':dt.datetime.now().isoformat(),
                    'auto_trade':False},stream,indent=2)
        except FileExistsError:
            return gp_permission(settings,output,claim=False)
    return {'allowed':True,'weekly_receipt':str(path)}


def queued_count(settings):
    identifiers=set()
    queue=Path(settings['queue'])
    for path in [*queue.glob('*.toml'),*(queue/'processing').glob('*.toml')]:
        content=tomllib.loads(path.read_text(encoding='utf-8'))
        for row in content.get('factors',[content]):
            if may_enqueue(row,settings):
                identifiers.add(row['id'])
    return len(identifiers)
