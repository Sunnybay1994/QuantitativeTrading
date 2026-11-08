#!/usr/bin/env python
"""Losslessly split oversized project Markdown while preserving old entry anchors.

This one-off maintenance tool uses only the Python standard library. It keeps
original bytes in artifacts/maintenance/docs_split_20261109/originals, writes
parts beside each source file, and replaces the old path with an anchor index.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


LIMIT_BYTES = 28 * 1024
TRIGGER_BYTES = 30 * 1024
BACKUP_REL = Path("artifacts/maintenance/docs_split_20261109")
FENCE_OPEN = re.compile(rb"^ {0,3}(`{3,}|~{3,})(.*?)(?:\r?\n)?$")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
CHECKER_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
LIST_MARKER = re.compile(r"^( *)(?:[-+*]|\d+[.)])\s+")
INLINE_CODE = re.compile(r"(`+).*?\1")
INLINE_LINK = re.compile(r"(\]\(\s*)(?:<)?(#[^\s)>]+)(?:>)?")
REFERENCE_LINK = re.compile(r"^(\s*\[[^\]]+\]:\s*)(?:<)?(#[^\s>]+)(?:>)?")
HTML_LINK = re.compile(r"((?:href|src)\s*=\s*[\"'])(#[^\"']+)([\"'])", re.I)
HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)\s*=\s*([\"'])(.*?)\1[^>]*>", re.I)
HTML_ID = re.compile(r"<[A-Za-z][^>]*\b(?:id|name)\s*=\s*([\"'])(.*?)\1[^>]*>", re.I)


@dataclass
class Piece:
    start: int
    end: int
    kind: str = "text"
    prefix: bytes = b""
    suffix: bytes = b""
    rendered: bytes = b""
    patches: list[dict] = field(default_factory=list)


@dataclass
class Block:
    start: int
    end: int
    kind: str
    first_line: int
    last_line: int
    closed: bool = True


class UnsafeSplit(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decode_line(line: bytes, first: bool = False) -> str:
    return line.decode("utf-8-sig" if first else "utf-8")


def line_offsets(lines: list[bytes]) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    offsets.append(cursor)
    return offsets


def fence_close(line: bytes, marker: bytes) -> bool:
    char = marker[:1].decode()
    count = len(marker)
    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
    return bool(re.match(r"^ {0,3}" + re.escape(char) + r"{" + str(count) + r",}\s*$", text))


def table_start(lines: list[bytes], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    first = decode_line(lines[index], first=index == 0).rstrip("\r\n")
    second = decode_line(lines[index + 1]).rstrip("\r\n")
    return "|" in first and TABLE_SEPARATOR.match(second) is not None


def parse_blocks(data: bytes) -> tuple[list[Block], list[bytes], list[int]]:
    lines = data.splitlines(keepends=True)
    offsets = line_offsets(lines)
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        start_i = i
        text = decode_line(lines[i], first=i == 0)
        open_match = FENCE_OPEN.match(lines[i])
        if open_match:
            marker = open_match.group(1)
            i += 1
            closed = False
            while i < len(lines):
                if fence_close(lines[i], marker):
                    i += 1
                    closed = True
                    break
                i += 1
            blocks.append(Block(offsets[start_i], offsets[i], "fence", start_i, i, closed))
            continue
        if table_start(lines, i):
            i += 2
            while i < len(lines):
                row = decode_line(lines[i]).rstrip("\r\n")
                if not row.strip() or "|" not in row:
                    break
                i += 1
            blocks.append(Block(offsets[start_i], offsets[i], "table", start_i, i))
            continue
        if not text.strip():
            i += 1
            while i < len(lines) and not decode_line(lines[i]).strip():
                i += 1
            blocks.append(Block(offsets[start_i], offsets[i], "blank", start_i, i))
            continue
        if HEADING.match(text.rstrip("\r\n")):
            i += 1
            blocks.append(Block(offsets[start_i], offsets[i], "heading", start_i, i))
            continue
        i += 1
        while i < len(lines):
            next_text = decode_line(lines[i]).rstrip("\r\n")
            if not next_text.strip() or FENCE_OPEN.match(lines[i]) or table_start(lines, i) or HEADING.match(next_text):
                break
            i += 1
        blocks.append(Block(offsets[start_i], offsets[i], "text", start_i, i))
    if not blocks and data:
        blocks.append(Block(0, len(data), "text", 0, len(lines)))
    if blocks and (blocks[0].start != 0 or blocks[-1].end != len(data)):
        raise UnsafeSplit("parser did not cover all source bytes")
    for left, right in zip(blocks, blocks[1:]):
        if left.end != right.start:
            raise UnsafeSplit("parser produced a source gap")
    return blocks, lines, offsets


def rewrite_line(line: bytes, linked_name: str, base_offset: int) -> tuple[bytes, list[dict]]:
    ending = b""
    body = line
    if body.endswith(b"\r\n"):
        ending, body = b"\r\n", body[:-2]
    elif body.endswith((b"\n", b"\r")):
        ending, body = body[-1:], body[:-1]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return line, []

    protected = [(m.start(), m.end()) for m in INLINE_CODE.finditer(text)]
    encoded_name = quote(linked_name, safe="-._~")
    candidates: list[tuple[int, int, str]] = []

    def not_protected(pos: int) -> bool:
        return not any(start <= pos < end for start, end in protected)

    for match in INLINE_LINK.finditer(text):
        if not_protected(match.start(2)):
            candidates.append((match.start(), match.end(), match.group(1) + "<" + encoded_name + match.group(2) + ">"))
    for match in REFERENCE_LINK.finditer(text):
        if not_protected(match.start(2)):
            candidates.append((match.start(), match.end(), match.group(1) + "<" + encoded_name + match.group(2) + ">"))
    for match in HTML_LINK.finditer(text):
        if not_protected(match.start(2)):
            candidates.append((match.start(), match.end(), match.group(1) + encoded_name + match.group(2) + match.group(3)))
    if not candidates:
        return line, []

    candidates.sort(key=lambda item: (item[0], item[1]))
    selected: list[tuple[int, int, str]] = []
    last_end = -1
    for candidate in candidates:
        if candidate[0] < last_end:
            continue
        selected.append(candidate)
        last_end = candidate[1]

    output = bytearray()
    patches: list[dict] = []
    cursor = 0
    for start, end, replacement in selected:
        output.extend(text[cursor:start].encode("utf-8"))
        before = text[start:end].encode("utf-8")
        after = replacement.encode("utf-8")
        patch_start = base_offset + len(output)
        output.extend(after)
        patches.append({"start": patch_start, "end": patch_start + len(after), "before_b64": b64(before), "after_b64": b64(after)})
        cursor = end
    output.extend(text[cursor:].encode("utf-8"))
    output.extend(ending)
    return bytes(output), patches


def transform_source(data: bytes, linked_name: str, disable_links: bool = False) -> tuple[bytes, list[dict]]:
    if disable_links:
        return data, []
    lines = data.splitlines(keepends=True)
    output = bytearray()
    patches: list[dict] = []
    in_fence = False
    marker = b""
    for line in lines:
        if in_fence:
            output.extend(line)
            if fence_close(line, marker):
                in_fence = False
                marker = b""
            continue
        opener = FENCE_OPEN.match(line)
        if opener:
            output.extend(line)
            in_fence = True
            marker = opener.group(1)
            continue
        rewritten, line_patches = rewrite_line(line, linked_name, len(output))
        output.extend(rewritten)
        patches.extend(line_patches)
    return bytes(output), patches


def split_fence(block: Block, lines: list[bytes], offsets: list[int], limit: int) -> list[Piece]:
    block_lines = lines[block.first_line:block.last_line]
    if not block_lines:
        raise UnsafeSplit("malformed code fence")
    opener = block_lines[0]
    if block.closed:
        if len(block_lines) < 2:
            raise UnsafeSplit("malformed code fence")
        closer = block_lines[-1]
        body = block_lines[1:-1]
    else:
        match = FENCE_OPEN.match(opener)
        if match is None or block.end != offsets[-1]:
            raise UnsafeSplit("only a final unterminated code fence can receive a generated closer")
        indent = opener[: len(opener) - len(opener.lstrip(b" "))]
        newline = b"\r\n" if opener.endswith(b"\r\n") else b"\n"
        closer = indent + match.group(1) + newline
        body = block_lines[1:]
    if len(opener) + len(closer) >= limit:
        raise UnsafeSplit("fence wrappers leave no safe body capacity")
    groups: list[tuple[int, int]] = []
    current_start = 0
    current_size = 0
    body_capacity = limit - len(opener) - len(closer)
    for idx, line in enumerate(body):
        if len(line) > body_capacity:
            raise UnsafeSplit("single code line exceeds safe volume capacity")
        if current_size + len(line) > body_capacity and current_size:
            groups.append((current_start, idx))
            current_start = idx
            current_size = 0
        current_size += len(line)
    if body:
        groups.append((current_start, len(body)))
    if len(groups) <= 1:
        if block.closed:
            return [Piece(block.start, block.end, "fence")]
        return [Piece(block.start, block.end, "fence_unclosed", suffix=closer)]
    result: list[Piece] = []
    body_line_base = block.first_line + 1
    for group_index, (lo, hi) in enumerate(groups):
        start = block.start if group_index == 0 else offsets[body_line_base + lo]
        end = offsets[body_line_base + hi]
        prefix = b"" if group_index == 0 else opener
        if block.closed and group_index == len(groups) - 1:
            end = block.end
            suffix = b""
        else:
            suffix = closer
        kind = "fence_split_unclosed" if not block.closed else "fence_split"
        result.append(Piece(start, end, kind, prefix, suffix))
    return result


def split_table(block: Block, lines: list[bytes], offsets: list[int], data: bytes, linked_name: str, limit: int) -> list[Piece]:
    table_lines = lines[block.first_line:block.last_line]
    if len(table_lines) < 2:
        raise UnsafeSplit("malformed Markdown table")
    header = table_lines[0] + table_lines[1]
    transformed_header, _ = transform_source(header, linked_name)
    if len(transformed_header) >= limit:
        raise UnsafeSplit("table header and separator exceed volume limit")
    rows = table_lines[2:]
    if not rows:
        return [Piece(block.start, block.end, "table")]
    table_rows_start = block.first_line + 2
    row_lengths = []
    for index, row in enumerate(rows):
        row_start = offsets[table_rows_start + index]
        row_end = offsets[table_rows_start + index + 1]
        rendered_row, _ = transform_source(data[row_start:row_end], linked_name)
        row_lengths.append(len(rendered_row))
    result: list[Piece] = []
    lo = 0
    while lo < len(rows):
        prefix = b"" if lo == 0 else transformed_header
        current_size = len(transformed_header) if lo == 0 else len(transformed_header)
        hi = lo
        while hi < len(rows) and current_size + row_lengths[hi] <= limit:
            current_size += row_lengths[hi]
            hi += 1
        if hi == lo:
            raise UnsafeSplit("one table row exceeds safe volume capacity")
        start_offset = block.start if lo == 0 else offsets[table_rows_start + lo]
        end_offset = offsets[table_rows_start + hi]
        result.append(Piece(start_offset, end_offset, "table", prefix=prefix))
        lo = hi
    if len(result) == 1 and len(data[block.start:block.end]) <= limit:
        return [Piece(block.start, block.end, "table")]
    if len(result) > 1:
        for piece in result:
            piece.kind = "table_split"
    return result


def balanced_markdown_line(text: str, inline_ticks: bool, brackets: int, parens: int) -> tuple[bool, int, int]:
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`":
            j = i + 1
            while j < len(text) and text[j] == "`":
                j += 1
            inline_ticks = not inline_ticks
            i = j
            continue
        if not inline_ticks:
            if text[i] == "[":
                brackets += 1
            elif text[i] == "]" and brackets:
                brackets -= 1
            elif text[i] == "(":
                parens += 1
            elif text[i] == ")" and parens:
                parens -= 1
        i += 1
    return inline_ticks, brackets, parens


def split_text(block: Block, lines: list[bytes], offsets: list[int], data: bytes, linked_name: str, limit: int) -> list[Piece]:
    source_lines = lines[block.first_line:block.last_line]
    if not source_lines:
        return [Piece(block.start, block.end, block.kind)]
    joined = b"".join(source_lines)
    if re.match(rb"(?s)^\s*<(?:!--|/?(?:div|details|table|section|pre|script|style|ul|ol|li)\b)", joined, re.I):
        raise UnsafeSplit("large HTML block requires manual boundary review")
    first_text = decode_line(source_lines[0], first=block.first_line == 0).rstrip("\r\n")
    first_marker = LIST_MARKER.match(first_text)
    list_indent = len(first_marker.group(1)) if first_marker else None
    all_quote_lines = all(re.match(r"^ {0,3}>", decode_line(line).lstrip("\ufeff")) for line in source_lines)
    safe_boundaries: list[int] = []
    inline_ticks = False
    brackets = 0
    parens = 0
    for idx, raw_line in enumerate(source_lines, start=1):
        text = decode_line(raw_line).rstrip("\r\n")
        inline_ticks, brackets, parens = balanced_markdown_line(text, inline_ticks, brackets, parens)
        if inline_ticks or brackets or parens or text.rstrip().endswith("\\"):
            continue
        if idx == len(source_lines):
            safe_boundaries.append(idx)
            continue
        next_text = decode_line(source_lines[idx]).rstrip("\r\n")
        if list_indent is not None:
            next_marker = LIST_MARKER.match(next_text)
            if next_marker and len(next_marker.group(1)) <= list_indent:
                safe_boundaries.append(idx)
        elif all_quote_lines:
            if re.match(r"^ {0,3}>", next_text):
                safe_boundaries.append(idx)
        else:
            safe_boundaries.append(idx)
    if not safe_boundaries:
        raise UnsafeSplit("no safe paragraph/list boundary below volume limit")

    rendered_line_lengths = []
    for line in source_lines:
        rendered, _ = transform_source(line, linked_name)
        rendered_line_lengths.append(len(rendered))
    prefix_sizes = [0]
    for size in rendered_line_lengths:
        prefix_sizes.append(prefix_sizes[-1] + size)
    result: list[Piece] = []
    start_line = 0
    boundary_index = 0
    while start_line < len(source_lines):
        while boundary_index < len(safe_boundaries) and safe_boundaries[boundary_index] <= start_line:
            boundary_index += 1
        chosen = None
        scan = boundary_index
        while scan < len(safe_boundaries):
            boundary = safe_boundaries[scan]
            if prefix_sizes[boundary] - prefix_sizes[start_line] > limit:
                break
            chosen = boundary
            scan += 1
        if chosen is None:
            raise UnsafeSplit("a paragraph or list item exceeds volume limit")
        end_line = chosen
        boundary_index = scan
        result.append(Piece(offsets[block.first_line + start_line], offsets[block.first_line + end_line], block.kind))
        start_line = end_line
    return result


def source_blocks(data: bytes, linked_name: str) -> list[Piece]:
    blocks, lines, offsets = parse_blocks(data)
    unclosed = [block for block in blocks if block.kind == "fence" and not block.closed]
    if unclosed and (len(unclosed) != 1 or unclosed[0] is not blocks[-1] or unclosed[0].end != len(data)):
        raise UnsafeSplit("only a single unterminated code fence at EOF can receive generated wrappers")
    pieces: list[Piece] = []
    for block in blocks:
        if block.kind == "fence" and not block.closed:
            pieces.extend(split_fence(block, lines, offsets, LIMIT_BYTES))
            continue
        raw = data[block.start:block.end]
        rendered, _ = transform_source(raw, linked_name, disable_links=block.kind == "fence")
        if len(rendered) <= LIMIT_BYTES:
            pieces.append(Piece(block.start, block.end, block.kind))
        elif block.kind == "fence":
            pieces.extend(split_fence(block, lines, offsets, LIMIT_BYTES))
        elif block.kind == "table":
            pieces.extend(split_table(block, lines, offsets, data, linked_name, LIMIT_BYTES))
        else:
            pieces.extend(split_text(block, lines, offsets, data, linked_name, LIMIT_BYTES))
    if pieces and (pieces[0].start != 0 or pieces[-1].end != len(data)):
        raise UnsafeSplit("split pieces do not cover source bytes")
    for left, right in zip(pieces, pieces[1:]):
        if left.end != right.start:
            raise UnsafeSplit("split pieces have a gap or overlap")
    for piece in pieces:
        source = data[piece.start:piece.end]
        transformed, patches = transform_source(source, linked_name, disable_links=piece.kind.startswith("fence"))
        piece.rendered = piece.prefix + transformed + piece.suffix
        piece.patches = patches
        if len(piece.rendered) > LIMIT_BYTES:
            raise UnsafeSplit("rendered source piece exceeds volume limit")
    return pieces


def pack_pieces(pieces: list[Piece]) -> list[list[Piece]]:
    volumes: list[list[Piece]] = []
    current: list[Piece] = []
    size = 0
    for piece in pieces:
        isolated = piece.kind in {"table_split", "fence_split", "fence_split_unclosed"}
        current_isolated = bool(current and current[-1].kind in {"table_split", "fence_split", "fence_split_unclosed"})
        if current and (isolated or current_isolated):
            volumes.append(current)
            current = []
            size = 0
        if current and size + len(piece.rendered) > LIMIT_BYTES:
            volumes.append(current)
            current = []
            size = 0
        current.append(piece)
        size += len(piece.rendered)
        if isolated:
            volumes.append(current)
            current = []
            size = 0
    if current:
        volumes.append(current)
    if any(sum(len(piece.rendered) for piece in volume) > LIMIT_BYTES for volume in volumes):
        raise UnsafeSplit("packed volume exceeds size limit")
    return volumes


def collect_heading_and_anchor_events(data: bytes) -> tuple[list[dict], list[dict]]:
    text = data.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    headings: list[dict] = []
    anchors: list[dict] = []
    offset = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    checker_fence: str | None = None
    slug_counts: Counter[str] = Counter()
    for line in lines:
        stripped = line.rstrip("\r\n")
        if checker_fence is not None:
            if re.match(r"^" + re.escape(checker_fence) + r"[^\n]*$", stripped):
                checker_fence = None
            offset += len(line.encode("utf-8"))
            continue
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match:
            checker_fence = fence_match.group(1)
            offset += len(line.encode("utf-8"))
            continue
        line_start = offset
        for match in HTML_ANCHOR.finditer(stripped):
            anchors.append({"offset": line_start + len(stripped[:match.start()].encode("utf-8")), "tag": match.group(0), "id": match.group(2)})
        for match in HTML_ID.finditer(stripped):
            if not HTML_ANCHOR.search(match.group(0)):
                anchors.append({"offset": line_start + len(stripped[:match.start()].encode("utf-8")), "tag": f'<a id="{match.group(2)}"></a>', "id": match.group(2)})
        match = CHECKER_HEADING.match(stripped)
        if match:
            title = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", match.group(1))
            base = re.sub(r"[^\w\s-]", "", title.lower()).replace(" ", "-")
            suffix = f"-{slug_counts[base]}" if slug_counts[base] else ""
            slug_counts[base] += 1
            level = len(re.match(r"^(#+)", stripped).group(1))
            headings.append({"offset": line_start, "line": stripped, "base_slug": base, "document_slug": base + suffix, "level": level})
        offset += len(line.encode("utf-8"))
    return headings, anchors


def locate_volume(offset: int, pieces_by_volume: list[list[Piece]]) -> int:
    for index, volume in enumerate(pieces_by_volume):
        for piece in volume:
            if piece.start <= offset < piece.end:
                return index
    if pieces_by_volume and offset == pieces_by_volume[-1][-1].end:
        return len(pieces_by_volume) - 1
    raise UnsafeSplit(f"anchor at byte {offset} has no volume")


def build_index(source_rel: str, part_names: list[str], headings: list[dict], anchors: list[dict], pieces_by_volume: list[list[Piece]]) -> bytes:
    part_urls = [quote(name, safe="-._~") for name in part_names]
    lines = [
        f"<!-- Split index for `{Path(source_rel).name}`; exact source bytes are backed up under `{BACKUP_REL.as_posix()}/originals`. -->",
        "原文分卷入口：" + " · ".join(f"[第 {i + 1} 卷]({url})" for i, url in enumerate(part_urls)),
        "",
    ]
    local_counts: list[Counter[str]] = [Counter() for _ in part_names]
    heading_links: dict[int, tuple[int, str]] = {}
    for heading in headings:
        vol = locate_volume(heading["offset"], pieces_by_volume)
        base = heading["base_slug"]
        suffix = f"-{local_counts[vol][base]}" if local_counts[vol][base] else ""
        local_counts[vol][base] += 1
        heading_links[heading["offset"]] = (vol, base + suffix)
    heading_spans = [
        (item["offset"], item["offset"] + len(item["line"].encode("utf-8")))
        for item in headings
    ]
    events: list[tuple[int, str, dict]] = []
    events.extend(
        (item["offset"], "anchor", item)
        for item in anchors
        if not any(start <= item["offset"] < end for start, end in heading_spans)
    )
    events.extend((item["offset"], "heading", item) for item in headings)
    events.sort(key=lambda item: (item[0], 0 if item[1] == "anchor" else 1))
    seen_anchor_locations: set[tuple[int, str]] = set()
    for offset, kind, item in events:
        vol = locate_volume(offset, pieces_by_volume)
        if kind == "anchor":
            tag = item["tag"]
            ident = item["id"]
            lines.append(tag)
            key = (offset, ident)
            if key not in seen_anchor_locations:
                frag = quote(ident, safe="-._~")
                lines.append(f"[原文锚点位置：第 {vol + 1} 卷]({part_urls[vol]}#{frag})")
                lines.append("")
                seen_anchor_locations.add(key)
        else:
            lines.append(item["line"])
            if item.get("level", 1) <= 2:
                target_vol, slug = heading_links[offset]
                frag = quote(slug, safe="-._~")
                lines.append(f"[↗]({part_urls[target_vol]}#{frag})")
    if not headings and not anchors:
        lines.append(f"[打开第 1 卷]({part_urls[0]})")
        lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def part_filename(source: Path, index: int) -> str:
    return f"{source.stem}.part-{index:02d}{source.suffix}"


def preflight_doc(root: Path, path: Path) -> dict:
    relative = path.relative_to(root).as_posix()
    source = path.read_bytes()
    digest = sha256(source)
    classification = "archive" if relative.startswith("docs/archive/") else "active"
    headings: list[dict] = []
    anchors: list[dict] = []
    index_size = None
    try:
        source.decode("utf-8-sig")
        pieces = source_blocks(source, path.name)
        volumes = pack_pieces(pieces)
        headings, anchors = collect_heading_and_anchor_events(source)
        part_names = [part_filename(path, i + 1) for i in range(len(volumes))]
        for name in part_names:
            if (path.parent / name).exists():
                raise UnsafeSplit(f"output already exists: {name}")
        index_data = build_index(relative, part_names, headings, anchors, volumes)
        index_size = len(index_data)
        if len(index_data) > LIMIT_BYTES:
            raise UnsafeSplit(f"anchor index would be {len(index_data)} bytes")
        return {
            "source_relative_path": relative,
            "classification": classification,
            "original_bytes": len(source),
            "original_sha256": digest,
            "status": "planned",
            "reason": None,
            "heading_count": len(headings),
            "explicit_anchor_count": len(anchors),
            "part_names": part_names,
            "part_sizes": [sum(len(p.rendered) for p in volume) for volume in volumes],
            "index_bytes": len(index_data),
            "pieces": pieces,
            "volumes": volumes,
            "index_data": index_data,
        }
    except (UnicodeDecodeError, UnsafeSplit) as exc:
        return {
            "source_relative_path": relative,
            "classification": classification,
            "original_bytes": len(source),
            "original_sha256": digest,
            "status": "unsplittable",
            "reason": str(exc),
            "heading_count": len(headings),
            "explicit_anchor_count": len(anchors),
            "part_names": [],
            "part_sizes": [],
            "index_bytes": index_size,
        }


def serializable_plan(plan: dict) -> dict:
    return {key: plan[key] for key in (
        "source_relative_path", "classification", "original_bytes", "original_sha256", "status", "reason",
        "heading_count", "explicit_anchor_count", "part_names", "part_sizes", "index_bytes"
    )}


def plan_counts(plans: list[dict]) -> dict:
    safe = [p for p in plans if p["status"] == "planned"]
    return {
        "candidate_count": len(plans),
        "active_count": sum(p["classification"] == "active" for p in plans),
        "archive_count": sum(p["classification"] == "archive" for p in plans),
        "planned_split_count": len(safe),
        "planned_volume_count": sum(len(p["part_names"]) for p in safe),
        "unsplittable_count": len(plans) - len(safe),
        "max_part_bytes": max((max(p["part_sizes"], default=0) for p in safe), default=0),
        "max_index_bytes": max((p["index_bytes"] or 0 for p in safe), default=0),
    }


def manifest_save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_new_bytes(path: Path, payload: bytes) -> None:
    """Create a file exclusively so an unexpected existing file is preserved."""
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(payload)
            stream.flush()
    except Exception:
        if created and path.exists():
            path.unlink()
        raise


def restore_source_if_unchanged(path: Path, backup: bytes, expected_current_sha256: str) -> None:
    """Restore a failed split only if the index still matches this tool's output."""
    if sha256(path.read_bytes()) != expected_current_sha256:
        raise OSError(f"source changed after split; refusing rollback overwrite: {path}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.restore-", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(backup)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256(path.read_bytes()) != expected_current_sha256:
            raise OSError(f"source changed during rollback; refusing overwrite: {path}")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def render_and_record(root: Path, plan: dict, source: bytes, dest_path: Path) -> dict:
    volume_records = []
    created: list[Path] = []
    index_tmp = dest_path.with_name(dest_path.name + ".split-index.tmp")
    index_tmp_created = False
    try:
        for vol_index, pieces in enumerate(plan["volumes"], start=1):
            name = plan["part_names"][vol_index - 1]
            part_path = dest_path.parent / name
            if part_path.exists():
                raise FileExistsError(f"refusing to overwrite existing part: {part_path}")
            rendered_volume = bytearray()
            piece_records = []
            for piece in pieces:
                start = len(rendered_volume)
                rendered_volume.extend(piece.prefix)
                content_start = len(rendered_volume)
                body_end = len(piece.rendered) - len(piece.suffix) if piece.suffix else len(piece.rendered)
                rendered_volume.extend(piece.rendered[len(piece.prefix):body_end])
                content_end = len(rendered_volume)
                rendered_volume.extend(piece.suffix)
                piece_records.append({
                    "source_start": piece.start,
                    "source_end": piece.end,
                    "source_sha256": sha256(source[piece.start:piece.end]),
                    "volume_start": start,
                    "content_start": content_start,
                    "content_end": content_end,
                    "volume_end": len(rendered_volume),
                    "synthetic_prefix_b64": b64(piece.prefix),
                    "synthetic_suffix_b64": b64(piece.suffix),
                    "link_rewrites": piece.patches,
                    "kind": piece.kind,
                    "synthetic_wrapper_reason": (
                        "close original EOF-unclosed fence for a balanced volume"
                        if piece.kind in {"fence_unclosed", "fence_split_unclosed"}
                        else None
                    ),
                })
            if len(rendered_volume) > LIMIT_BYTES:
                raise UnsafeSplit(f"rendered volume {name} exceeds size limit")
            write_new_bytes(part_path, bytes(rendered_volume))
            created.append(part_path)
            reread = part_path.read_bytes()
            if reread != bytes(rendered_volume):
                raise OSError(f"written volume failed byte check: {name}")
            volume_records.append({
                "path": part_path.relative_to(root).as_posix(),
                "bytes": len(reread),
                "sha256": sha256(reread),
                "source_ranges": [{"start": p.start, "end": p.end} for p in pieces],
                "pieces": piece_records,
            })

        write_new_bytes(index_tmp, plan["index_data"])
        index_tmp_created = True
        if len(index_tmp.read_bytes()) != len(plan["index_data"]):
            raise OSError("index temporary file failed byte check")
        if sha256(dest_path.read_bytes()) != plan["original_sha256"]:
            raise OSError("source changed after backup; refusing to replace")
        os.replace(index_tmp, dest_path)
        index_tmp_created = False
        return {
            "status": "split",
            "reason": None,
            "index_bytes": dest_path.stat().st_size,
            "index_sha256": sha256(dest_path.read_bytes()),
            "volumes": volume_records,
            "created_parts": created,
        }
    except Exception:
        if index_tmp_created:
            index_tmp.unlink(missing_ok=True)
        for part in created:
            part.unlink(missing_ok=True)
        raise


def validate_split_file(root: Path, entry: dict) -> dict:
    backup = (root / entry["backup_relative_path"]).read_bytes()
    if sha256(backup) != entry["original_sha256"]:
        return {"ok": False, "reason": "backup hash mismatch"}
    if entry["status"] == "unsplittable":
        original = (root / entry["source_relative_path"]).read_bytes()
        if original != backup:
            return {"ok": False, "reason": "unsplittable source differs from backup"}
        return {"ok": True, "restored_sha256": sha256(backup), "source_bytes": len(backup)}
    reconstructed = bytearray()
    expected_start = 0
    for volume in entry["volumes"]:
        part_path = root / volume["path"]
        content = part_path.read_bytes()
        if len(content) != volume["bytes"] or sha256(content) != volume["sha256"]:
            return {"ok": False, "reason": f"volume hash or size mismatch: {volume['path']}"}
        if len(content) > LIMIT_BYTES:
            return {"ok": False, "reason": f"volume exceeds limit: {volume['path']}"}
        parsed_blocks, _, _ = parse_blocks(content)
        if any(block.kind == "fence" and not block.closed for block in parsed_blocks):
            return {"ok": False, "reason": f"unbalanced code fence: {volume['path']}"}
        for piece in volume["pieces"]:
            if piece["source_start"] != expected_start:
                return {"ok": False, "reason": "source ranges are not contiguous"}
            prefix = base64.b64decode(piece["synthetic_prefix_b64"])
            suffix = base64.b64decode(piece["synthetic_suffix_b64"])
            if content[piece["volume_start"]:piece["content_start"]] != prefix:
                return {"ok": False, "reason": f"synthetic prefix mismatch: {volume['path']}"}
            if content[piece["content_end"]:piece["volume_end"]] != suffix:
                return {"ok": False, "reason": f"synthetic suffix mismatch: {volume['path']}"}
            if piece.get("kind") == "table_split":
                rendered_piece = content[piece["volume_start"]:piece["volume_end"]]
                table_blocks, table_lines, _ = parse_blocks(rendered_piece)
                if not table_blocks or table_blocks[0].kind != "table" or not table_start(table_lines, 0):
                    return {"ok": False, "reason": f"split table header or separator invalid: {volume['path']}"}
                if prefix and table_lines[:2] != prefix.splitlines(keepends=True):
                    return {"ok": False, "reason": f"repeated table header mismatch: {volume['path']}"}
            segment = bytearray(content[piece["content_start"]:piece["content_end"]])
            for patch in sorted(piece["link_rewrites"], key=lambda item: item["start"], reverse=True):
                start, end = patch["start"], patch["end"]
                after = base64.b64decode(patch["after_b64"])
                before = base64.b64decode(patch["before_b64"])
                if segment[start:end] != after:
                    return {"ok": False, "reason": f"link rewrite mismatch: {volume['path']}"}
                segment[start:end] = before
            source_slice = backup[piece["source_start"]:piece["source_end"]]
            if bytes(segment) != source_slice or sha256(bytes(segment)) != piece["source_sha256"]:
                return {"ok": False, "reason": f"source range reconstruction mismatch: {volume['path']}"}
            reconstructed.extend(segment)
            expected_start = piece["source_end"]
    if bytes(reconstructed) != backup or sha256(bytes(reconstructed)) != entry["original_sha256"]:
        return {"ok": False, "reason": "full source restoration mismatch"}
    index_path = root / entry["source_relative_path"]
    if index_path.stat().st_size > LIMIT_BYTES or sha256(index_path.read_bytes()) != entry["index_sha256"]:
        return {"ok": False, "reason": "index size or hash mismatch"}
    return {"ok": True, "restored_sha256": sha256(bytes(reconstructed)), "source_bytes": len(reconstructed)}


def target_files(root: Path) -> list[Path]:
    docs = root / "docs"
    candidates = []
    for path in docs.rglob("*.md"):
        if re.search(r"\.part-\d+\.md$", path.name):
            continue
        if path.stat().st_size > TRIGGER_BYTES:
            candidates.append(path)
    candidates.sort(key=lambda p: ("/archive/" in p.as_posix(), p.as_posix().casefold()))
    return candidates


def refresh_manifest_summary(manifest: dict) -> None:
    entries = manifest.get("files", [])
    split = [entry for entry in entries if entry.get("status") == "split"]
    unsplittable = [entry for entry in entries if entry.get("status") == "unsplittable"]
    summary = manifest.setdefault("summary", {})
    summary.update({
        "candidate_count": len(entries),
        "active_count": sum(entry.get("classification") == "active" for entry in entries),
        "archive_count": sum(entry.get("classification") == "archive" for entry in entries),
        "planned_split_count": len(split),
        "planned_volume_count": sum(len(entry.get("volumes", [])) for entry in split),
        "unsplittable_count": len(unsplittable),
        "split_count": len(split),
        "verified_count": sum(bool(entry.get("restore_validation", {}).get("ok")) for entry in split),
        "max_part_bytes": max((volume.get("bytes", 0) for entry in split for volume in entry.get("volumes", [])), default=0),
        "max_index_bytes": max((entry.get("index_bytes", 0) for entry in split), default=0),
    })
    manifest["status"] = "applied_with_unsplittable" if unsplittable else "applied"


def resume_unsplittable(root: Path, manifest_path: Path) -> int:
    if not manifest_path.is_file():
        print(json.dumps({"resumed": False, "reason": "manifest missing"}, ensure_ascii=False))
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pending = [entry for entry in manifest.get("files", []) if entry.get("status") == "unsplittable"]
    if len(pending) != 1:
        print(json.dumps({"resumed": False, "reason": f"expected one unsplittable entry; found {len(pending)}"}, ensure_ascii=False))
        return 2

    entry = pending[0]
    source_path = root / entry["source_relative_path"]
    backup_path = root / entry["backup_relative_path"]
    if not source_path.is_file() or not backup_path.is_file():
        print(json.dumps({"resumed": False, "reason": "source or backup missing"}, ensure_ascii=False))
        return 2
    source = source_path.read_bytes()
    backup = backup_path.read_bytes()
    if sha256(backup) != entry["original_sha256"] or source != backup:
        print(json.dumps({"resumed": False, "reason": "source no longer matches the exact original backup"}, ensure_ascii=False))
        return 2

    plan = preflight_doc(root, source_path)
    if plan.get("status") != "planned":
        entry["reason"] = plan.get("reason") or "preflight remains unsplittable"
        entry["restore_validation"] = validate_split_file(root, entry)
        refresh_manifest_summary(manifest)
        manifest_save(manifest_path, manifest)
        print(json.dumps({"resumed": False, "reason": entry["reason"], "summary": manifest["summary"]}, ensure_ascii=False))
        return 1
    if plan["original_sha256"] != entry["original_sha256"] or plan["original_bytes"] != entry["original_bytes"]:
        print(json.dumps({"resumed": False, "reason": "preflight original hash or size changed"}, ensure_ascii=False))
        return 2
    collisions = [name for name in plan["part_names"] if (source_path.parent / name).exists()]
    if collisions:
        print(json.dumps({"resumed": False, "reason": "planned part already exists", "count": len(collisions)}, ensure_ascii=False))
        return 2

    entry["previous_validation_failure"] = entry.get("validation_failure")
    entry["part_names"] = plan["part_names"]
    entry["part_sizes"] = plan["part_sizes"]
    entry["index_bytes"] = plan["index_bytes"]
    entry["heading_count"] = plan["heading_count"]
    entry["explicit_anchor_count"] = plan["explicit_anchor_count"]
    entry["status"] = "resuming"
    entry["reason"] = "rebuilding only the original unsplittable source with a recorded synthetic EOF fence closer"
    manifest["status"] = "resuming"
    manifest_save(manifest_path, manifest)

    try:
        rendered = render_and_record(root, plan, source, source_path)
        entry.update({key: value for key, value in rendered.items() if key != "created_parts"})
        entry["status"] = "split"
        entry["reason"] = None
        entry.pop("validation_failure", None)
        validation = validate_split_file(root, entry)
        entry["restore_validation"] = validation
        if not validation["ok"]:
            restore_source_if_unchanged(source_path, backup, entry["index_sha256"])
            for volume in entry.get("volumes", []):
                part_path = root / volume["path"]
                if part_path.is_file() and sha256(part_path.read_bytes()) == volume["sha256"]:
                    part_path.unlink()
            entry["status"] = "unsplittable"
            entry["reason"] = "resumed split failed byte restoration or Markdown structure validation"
            entry["restore_validation"] = validate_split_file(root, entry)
            entry.pop("volumes", None)
            entry.pop("index_sha256", None)
        else:
            entry["synthetic_wrapper_policy"] = "synthetic fence bytes are stored in each piece prefix/suffix and excluded during restoration"
    except Exception as exc:
        expected_index_sha = sha256(plan["index_data"])
        if source_path.is_file() and sha256(source_path.read_bytes()) == expected_index_sha:
            try:
                restore_source_if_unchanged(source_path, backup, expected_index_sha)
            except OSError as rollback_exc:
                exc = RuntimeError(f"{exc}; rollback preserved concurrent source edit: {rollback_exc}")
        entry["status"] = "unsplittable"
        entry["reason"] = f"resumed apply failed safely: {type(exc).__name__}: {exc}"
        entry["restore_validation"] = validate_split_file(root, entry) if source_path.read_bytes() == backup else {"ok": False, "reason": "source differs from original backup"}
        entry.pop("volumes", None)
        entry.pop("index_sha256", None)

    refresh_manifest_summary(manifest)
    manifest_save(manifest_path, manifest)
    print(json.dumps({"resumed": entry.get("status") == "split", "summary": manifest["summary"], "source": entry["source_relative_path"], "reason": entry.get("reason")}, ensure_ascii=False))
    return 0 if entry.get("status") == "split" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--resume-unsplittable", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    backup_root = root / BACKUP_REL
    manifest_path = backup_root / "manifest.json"

    if args.resume_unsplittable:
        return resume_unsplittable(root, manifest_path)

    if args.verify:
        if not manifest_path.is_file():
            print(json.dumps({"verified": False, "reason": "manifest missing"}, ensure_ascii=False))
            return 2
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results = [
            {"source": entry["source_relative_path"], **validate_split_file(root, entry)}
            for entry in manifest.get("files", [])
        ]
        ok = all(result.get("ok") for result in results)
        print(json.dumps({"verified": ok, "files": len(results), "failed": sum(not r.get("ok") for r in results)}, ensure_ascii=False))
        return 0 if ok else 1

    paths = target_files(root)
    plans = [preflight_doc(root, path) for path in paths]
    summary = {
        "candidate_count": len(plans),
        "active_count": sum(p["classification"] == "active" for p in plans),
        "archive_count": sum(p["classification"] == "archive" for p in plans),
        "planned_split_count": sum(p["status"] == "planned" for p in plans),
        "planned_volume_count": sum(len(p["part_names"]) for p in plans if p["status"] == "planned"),
        "unsplittable_count": sum(p["status"] != "planned" for p in plans),
        "max_part_bytes": max((max(p["part_sizes"], default=0) for p in plans), default=0),
        "max_index_bytes": max((p["index_bytes"] or 0 for p in plans if p["status"] == "planned"), default=0),
    }
    if args.dry_run:
        backup_root.mkdir(parents=True, exist_ok=True)
        dry_path = backup_root / "dry_run.json"
        if dry_path.exists():
            dry_path = backup_root / f"dry_run_{len(list(backup_root.glob('dry_run_*.json'))) + 1:02d}.json"
        result = {"summary": summary, "files": [serializable_plan(plan) for plan in plans]}
        dry_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "dry_run": True,
            "summary": summary,
            "unsplittable": [{"path": p["source_relative_path"], "reason": p["reason"]} for p in plans if p["status"] != "planned"],
            "report": dry_path.relative_to(root).as_posix(),
        }, ensure_ascii=False))
        return 0

    if manifest_path.exists() or (backup_root / "originals").exists():
        print(json.dumps({"applied": False, "reason": "backup or manifest already exists; refusing to overwrite"}, ensure_ascii=False))
        return 2
    backup_root.mkdir(parents=True, exist_ok=True)
    originals_dir = backup_root / "originals"
    originals_dir.mkdir(parents=True, exist_ok=False)
    plan_lookup = {plan["source_relative_path"]: plan for plan in plans}
    manifest_files = []
    for plan in plans:
        source_path = root / plan["source_relative_path"]
        source = source_path.read_bytes()
        if sha256(source) != plan["original_sha256"]:
            raise RuntimeError(f"source changed during preflight: {plan['source_relative_path']}")
        backup_name = f"{plan['original_sha256'][:16]}__{source_path.name}"
        backup_path = originals_dir / backup_name
        if backup_path.exists():
            raise FileExistsError(f"backup already exists: {backup_path}")
        write_new_bytes(backup_path, source)
        if backup_path.read_bytes() != source:
            raise OSError(f"backup byte verification failed: {plan['source_relative_path']}")
        plan["backup_relative_path"] = backup_path.relative_to(root).as_posix()
        initial_status = "unsplittable" if plan["status"] == "unsplittable" else "backed_up"
        entry = {key: plan.get(key) for key in (
            "source_relative_path", "classification", "original_bytes", "original_sha256", "reason",
            "heading_count", "explicit_anchor_count", "part_names", "part_sizes", "index_bytes", "backup_relative_path"
        )}
        entry["status"] = initial_status
        manifest_files.append(entry)
    manifest = {
        "schema_version": 1,
        "status": "backed_up",
        "source_root": "docs",
        "backup_root": BACKUP_REL.as_posix(),
        "trigger_bytes": TRIGGER_BYTES,
        "max_volume_and_index_bytes": LIMIT_BYTES,
        "summary": {**summary, "split_count": 0, "verified_count": 0},
        "files": manifest_files,
    }
    manifest_save(manifest_path, manifest)

    for entry in manifest["files"]:
        if entry["status"] == "unsplittable":
            continue
        plan = plan_lookup[entry["source_relative_path"]]
        source_path = root / entry["source_relative_path"]
        source = source_path.read_bytes()
        try:
            rendered = render_and_record(root, plan, source, source_path)
            entry.update({key: value for key, value in rendered.items() if key != "created_parts"})
            entry["status"] = "split"
            validation = validate_split_file(root, entry)
            entry["restore_validation"] = validation
            if not validation["ok"]:
                backup = (root / entry["backup_relative_path"]).read_bytes()
                restore_source_if_unchanged(source_path, backup, entry["index_sha256"])
                for volume in entry.get("volumes", []):
                    part_path = root / volume["path"]
                    if part_path.is_file() and sha256(part_path.read_bytes()) == volume["sha256"]:
                        part_path.unlink()
                entry["status"] = "unsplittable"
                entry["reason"] = "post-write restoration validation failed: " + validation["reason"]
            else:
                manifest["summary"]["split_count"] += 1
                manifest["summary"]["verified_count"] += 1
        except Exception as exc:
            expected_index_sha256 = sha256(plan["index_data"])
            backup = (root / entry["backup_relative_path"]).read_bytes()
            if source_path.is_file() and sha256(source_path.read_bytes()) == expected_index_sha256:
                try:
                    restore_source_if_unchanged(source_path, backup, expected_index_sha256)
                except OSError as rollback_exc:
                    exc = RuntimeError(f"{exc}; rollback preserved concurrent source edit: {rollback_exc}")
            entry["status"] = "unsplittable"
            entry["reason"] = f"apply failed safely: {type(exc).__name__}: {exc}"
            entry["restore_validation"] = {"ok": False, "reason": entry["reason"]}
        manifest["summary"]["unsplittable_count"] = sum(item["status"] == "unsplittable" for item in manifest["files"])
        manifest["status"] = "applying"
        manifest_save(manifest_path, manifest)

    manifest["status"] = "applied_with_unsplittable" if manifest["summary"]["unsplittable_count"] else "applied"
    manifest_save(manifest_path, manifest)
    print(json.dumps({"applied": True, "summary": manifest["summary"], "manifest": manifest_path.relative_to(root).as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
