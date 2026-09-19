"""Freeze a registered one-shot search when a new continuous batch is created."""
import json
import tomllib
from pathlib import Path


def freeze_recipe(source: str, run: Path, final_run: Path, batches: list[Path]) -> str:
    requested = tomllib.loads(source).get('one_shot_search_config')
    if not requested:
        return source
    recipe_text = Path(requested).read_text(encoding='utf-8')
    recipe = tomllib.loads(recipe_text)
    if recipe['maximum_batches'] != 1:
        raise ValueError('One-shot search requires exactly one registered batch')
    filenames = ('cross_stock.toml', 'predictive_priority.toml')
    consumed = any(tomllib.loads(p.read_text(encoding='utf-8')).get('version') == recipe['version']
                   for prior in batches for name in filenames for p in prior.glob(f'????-??-??/{name}'))
    if consumed:
        return source
    if recipe['version'] == 'predictive_priority_v2':
        if recipe.get('stage') != 'scheduled_one_shot' or not recipe.get('enqueue') or recipe.get('auto_trade'):
            raise ValueError('Predictive-priority recipe must be explicitly activated')
        from quant.research.gp_predictive_priority import SelectionRules
        SelectionRules.from_config(recipe)
        manifest_path = Path(recipe['mechanism_manifest_file'])
        # Freezing the actual document, not a pointer to a mutable global file.
        from quant.research.gp_mechanism_inputs import read_mechanism_document
        from quant.research.predictive_priority_inputs import manifest_files
        manifest = read_mechanism_document(manifest_path)
        from quant.research.gp_predictive_priority import MechanismManifest, MechanismTerminal
        declared = MechanismManifest(tuple(MechanismTerminal(**row) for row in manifest['terminals']))
        if declared.sha256 != manifest['manifest_sha256']:
            raise ValueError('Mechanism manifest checksum differs')
        (run / 'predictive_priority.toml').write_text(recipe_text, encoding='utf-8')
        (run / 'predictive_manifest.json').write_bytes(manifest_path.read_bytes())
        for shard in manifest_files(manifest_path)[1:]:
            (run / shard.name).write_bytes(shard.read_bytes())
        return (f'predictive_priority_config = {json.dumps(str(final_run / "predictive_priority.toml"))}\n'
                f'predictive_priority_manifest = {json.dumps(str(final_run / "predictive_manifest.json"))}\n' + source)
    (run / 'cross_stock.toml').write_text(recipe_text, encoding='utf-8')
    return f'cross_stock_config = {json.dumps(str(final_run / "cross_stock.toml"))}\n' + source
