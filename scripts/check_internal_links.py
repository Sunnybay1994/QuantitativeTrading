"""Check local Markdown source links; report generated data/artifact links separately."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit


def anchors(path: Path) -> set[str]:
    source = path.read_text(encoding='utf-8-sig')
    source = re.sub(r'^(`{3,}|~{3,}).*?^\1[^\n]*$', '', source, flags=re.M | re.S)
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', source))
    counts = Counter()
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', source, flags=re.M):
        heading = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', heading)
        slug = re.sub(r'[^\w\s-]', '', heading.lower()).replace(' ', '-')
        suffix = f'-{counts[slug]}' if counts[slug] else ''
        result.add(slug+suffix)
        counts[slug] += 1
    return result


def check(root: Path) -> dict:
    names = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root
    ).decode('utf-8').split('\0')
    documents = sorted({name for name in names if name.endswith('.md') and (root/name).is_file()})
    broken, generated, outside, broken_anchors = [], [], [], []
    anchor_cache = {}
    checked = 0
    for name in documents:
        text = (root/name).read_text(encoding='utf-8-sig')
        text = re.sub(r'^(`{3,}|~{3,}).*?^\1[^\n]*$', '', text, flags=re.M | re.S)
        text = re.sub(r'`+[^`\n]*`+', '', text)
        refs = re.findall(r'!?\[[^\]\n]*\]\((<[^>]+>|[^\s\n)]+)(?:\s+"[^"]*")?\)', text)
        refs += re.findall(r'^\s*\[(?!\^)[^\]]+\]:\s*(<[^>]+>|\S+)', text, flags=re.M)
        refs += re.findall(r'(?:href|src)=["\']([^"\']+)["\']', text)
        for raw in refs:
            raw = raw.strip('<>')
            if not raw or urlsplit(raw).scheme:
                continue
            path = unquote(raw.split('#', 1)[0].split('?', 1)[0]).replace('\\', '/')
            path = re.sub(r':\d+(?::\d+)?$', '', path)
            target = (((root if path.startswith('/') else (root/name).parent)/path.lstrip('/')).resolve()
                      if path else (root/name).resolve())
            record = dict(source=name, link=raw)
            try:
                relative = target.relative_to(root).as_posix()
            except ValueError:
                outside.append(record)
                continue
            checked += 1
            if target.exists():
                fragment = unquote(raw.partition('#')[2])
                if fragment and target.suffix == '.md':
                    if target not in anchor_cache:
                        anchor_cache[target] = anchors(target)
                    if fragment not in anchor_cache[target]:
                        broken_anchors.append({**record, 'target':relative, 'fragment':fragment})
                continue
            if relative.startswith(('artifacts/', 'data/raw/', 'data/clean/', 'data/factors/', 'data/features/', 'data/qlib/', 'mlruns/')):
                generated.append(record)
            else:
                broken.append({**record, 'target':relative})
    return dict(documents=len(documents), checked=checked, broken=broken,
                broken_anchors=broken_anchors, generated_unavailable=generated, outside_workspace=outside)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = check(args.root.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in result.items()},ensure_ascii=False))
    return int(bool(result['broken'] or result['outside_workspace'] or result['broken_anchors']))


if __name__ == '__main__':
    raise SystemExit(main())
