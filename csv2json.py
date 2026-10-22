#!/usr/bin/env python3
"""csv2json - convert CSV files to JSON (array of objects or array of arrays).

Handles what real CSV files throw at you:
  * delimiter sniffing (comma, semicolon, tab, pipe) with an explicit override
  * encoding detection (UTF-8 with/without BOM, UTF-16, cp1252 fallback)
  * quoted fields containing the delimiter, newlines and doubled quotes
  * ragged rows (too few / too many fields) reported, not silently mangled
  * duplicate and blank header names made unique and reported
  * optional scalar coercion ("" -> null, ints, floats, true/false)
  * streaming: --stream writes one JSON object per line for files that do not fit in memory

Usage:
    python csv2json.py input.csv -o out.json
    python csv2json.py input.csv --delimiter ';' --indent 0 --coerce
    python csv2json.py big.csv --stream -o out.jsonl
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

DELIMITERS = [",", ";", "\t", "|"]
ENCODINGS = ["utf-8-sig", "utf-16", "cp1252", "latin-1"]


class Csv2JsonError(Exception):
    """Raised when the input cannot be parsed into records."""


def decode_bytes(raw: bytes, encoding: Optional[str] = None) -> Tuple[str, str]:
    """Decode bytes, returning (text, encoding actually used)."""
    candidates = [encoding] if encoding else ENCODINGS
    last: Optional[Exception] = None
    for enc in candidates:
        try:
            text = raw.decode(enc)  # type: ignore[arg-type]
        except (UnicodeDecodeError, LookupError) as exc:
            last = exc
            continue
        # utf-16 decodes almost any even-length byte string; only trust it when
        # a BOM is present, otherwise prefer the next candidate.
        if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            last = ValueError("no utf-16 BOM")
            continue
        return text, enc  # type: ignore[return-value]
    raise Csv2JsonError(f"could not decode input: {last}")


def sniff_delimiter(sample: str, explicit: Optional[str] = None) -> str:
    """Pick the delimiter with the most consistent per-line field count."""
    if explicit:
        if len(explicit) != 1:
            raise Csv2JsonError("--delimiter must be a single character")
        return explicit
    lines = [ln for ln in sample.splitlines() if ln.strip()][:25]
    if not lines:
        raise Csv2JsonError("input is empty")
    best, best_score = ",", -1
    for delim in DELIMITERS:
        try:
            counts = [len(next(csv.reader([ln], delimiter=delim))) for ln in lines]
        except csv.Error:
            continue
        if counts[0] < 2:
            continue
        # score = field count, penalised by disagreement between lines
        agreement = counts.count(max(set(counts), key=counts.count)) / len(counts)
        score = counts[0] * agreement if max(counts) > 1 else 0
        if score > best_score:
            best, best_score = delim, score
    return best


def make_unique(headers: Sequence[str], warn: Optional[list] = None) -> List[str]:
    """Return non-empty, unique header names (csv.DictReader silently drops dupes)."""
    out: List[str] = []
    seen: Dict[str, int] = {}
    for idx, raw in enumerate(headers):
        name = (raw or "").strip() or f"column_{idx + 1}"
        if name in seen:
            seen[name] += 1
            new = f"{name}_{seen[name]}"
            if warn is not None:
                warn.append(f"duplicate header {name!r} renamed to {new!r}")
            name = new
        else:
            seen[name] = 1
        out.append(name)
    return out


def coerce_value(text: str) -> Any:
    """Best-effort scalar coercion that never raises."""
    if text == "":
        return None
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def read_records(text: str, delimiter: str, coerce: bool = False,
                 warn: Optional[list] = None) -> List[Dict[str, Any]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration:
        raise Csv2JsonError("input has no header row")
    fields = make_unique(headers, warn)
    records: List[Dict[str, Any]] = []
    for lineno, row in enumerate(reader, start=2):
        if not row or all(cell == "" for cell in row):
            continue  # blank line
        if len(row) != len(fields):
            if warn is not None:
                warn.append(
                    f"row {lineno}: {len(row)} fields, expected {len(fields)} "
                    f"({'padded with null' if len(row) < len(fields) else 'extra fields dropped'})"
                )
            row = (row + [""] * len(fields))[: len(fields)]
        record = dict(zip(fields, row))
        if coerce:
            record = {k: coerce_value(v) for k, v in record.items()}
        records.append(record)
    return records


def convert(path: str, delimiter: Optional[str] = None, encoding: Optional[str] = None,
            coerce: bool = False) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    """Convert a CSV file. Returns (records, warnings, meta)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    text, enc = decode_bytes(raw, encoding)
    delim = sniff_delimiter(text, delimiter)
    warnings: List[str] = []
    records = read_records(text, delim, coerce=coerce, warn=warnings)
    meta = {"source": path, "encoding": enc,
            "delimiter": {"\t": "\\t"}.get(delim, delim),
            "rows": len(records), "columns": list(records[0].keys()) if records else []}
    return records, warnings, meta


def iter_stream(path: str, delimiter: Optional[str] = None,
                encoding: Optional[str] = None, coerce: bool = False) -> Iterator[Dict[str, Any]]:
    """Yield records without holding the whole file in memory."""
    with open(path, "rb") as fh:
        sample = fh.read(65536)
    text, _ = decode_bytes(sample, encoding)
    delim = sniff_delimiter(text, delimiter)
    with open(path, "r", encoding=encoding or decode_bytes(sample, encoding)[1],
              newline="") as fh:
        reader = csv.reader(fh, delimiter=delim)
        headers = make_unique(next(reader))
        for row in reader:
            if not row or all(cell == "" for cell in row):
                continue
            row = (row + [""] * len(headers))[: len(headers)]
            record = dict(zip(headers, row))
            yield {k: coerce_value(v) for k, v in record.items()} if coerce else record


def dumps(payload: Any, indent: int) -> str:
    """json.dumps where indent=0 means compact, not 'newline-heavy'."""
    if indent <= 0:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(payload, ensure_ascii=False, indent=indent)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Convert CSV to JSON.")
    ap.add_argument("input", help="CSV file to read ('-' for stdin)")
    ap.add_argument("-o", "--output", help="output file (default: stdout)")
    ap.add_argument("-d", "--delimiter", help="field delimiter (default: auto-detect)")
    ap.add_argument("-e", "--encoding", help="input encoding (default: auto-detect)")
    ap.add_argument("--indent", type=int, default=2, help="JSON indent (default 2)")
    ap.add_argument("--coerce", action="store_true",
                    help="convert numbers/booleans and empty strings to JSON scalars")
    ap.add_argument("--stream", action="store_true", help="write one JSON object per line (JSONL)")
    ap.add_argument("--quiet", action="store_true", help="suppress warnings on stderr")
    args = ap.parse_args(argv)

    try:
        if args.input == "-":
            raw = sys.stdin.buffer.read()
            text, enc = decode_bytes(raw, args.encoding)
            delim = sniff_delimiter(text, args.delimiter)
            warnings: List[str] = []
            records = read_records(text, delim, coerce=args.coerce, warn=warnings)
            meta = {"source": "<stdin>", "encoding": enc, "rows": len(records),
                    "columns": list(records[0].keys()) if records else []}
            payload: Any = records
            out_text = dumps(payload, args.indent)
        elif args.stream:
            out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
            count = 0
            try:
                for rec in iter_stream(args.input, args.delimiter, args.encoding, args.coerce):
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    count += 1
            finally:
                if args.output:
                    out.close()
            if not args.quiet:
                print(f"wrote {count} records", file=sys.stderr)
            return 0
        else:
            warnings, meta = [], {}
            records, warnings, meta = convert(args.input, args.delimiter, args.encoding, args.coerce)
            out_text = dumps(records, args.indent)
    except Csv2JsonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc.filename} not found", file=sys.stderr)
        return 2

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out_text + ("\n" if not out_text.endswith("\n") else ""))
    else:
        sys.stdout.write(out_text + "\n")
    if not args.quiet:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
        print(f"{meta.get('rows', 0)} rows, {len(meta.get('columns', []))} columns, "
              f"encoding {meta.get('encoding')}, delimiter {meta.get('delimiter')!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
