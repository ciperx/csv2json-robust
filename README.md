# csv2json

Convert CSV files to JSON — correctly, on real-world files, from the command line.

```bash
python csv2json.py input.csv -o out.json
python csv2json.py input.csv --delimiter ';' --coerce --indent 0
python csv2json.py big.csv --stream -o out.jsonl
```

## What it handles

| Problem in the wild | Behaviour |
|---|---|
| `,` `;` tab `\|` delimiters | auto-detected by per-line field-count agreement, or forced with `--delimiter` |
| UTF-8, UTF-8 BOM, UTF-16, cp1252, latin-1 | auto-detected (UTF-16 only trusted with a BOM), or forced with `--encoding` |
| Quoted fields containing the delimiter, newlines, `""` escapes | parsed by the `csv` module, not by `split()` |
| Duplicate or blank header names | made unique (`id`, `id_2`) and reported on stderr |
| Rows with too few / too many fields | padded with `null` / extra fields dropped, each reported with its line number |
| Blank lines | skipped |
| Numbers, booleans, empty strings | converted to JSON scalars with `--coerce` (default: everything stays a string) |
| Files too large for memory | `--stream` writes one JSON object per line (JSONL) |
| stdin | pass `-` as the input path |

## Output shape

Default: a JSON array of objects, one per CSV row, keyed by header.

```json
[{"name": "alice", "age": "30"}, {"name": "bob", "age": "41"}]
```

`--indent 0` gives a single compact line. `--indent N` pretty-prints at depth N.

## Exit codes

| code | meaning |
|---|---|
| 0 | converted |
| 2 | input error (missing file, undecodable bytes, empty input) — message on stderr, nothing partial on stdout |

## Tests

```bash
python -m pytest -q      # 11 tests
```

Covers delimiter auto-detection, quoted delimiters and embedded newlines, escaped quotes, unicode,
BOM input, duplicate/blank headers, ragged rows, scalar coercion, streaming, stdin and the
missing-file path.

## Design notes

* **No dependencies** — standard library only (`csv`, `json`, `argparse`, `io`). Runs on Python 3.8+.
* **Never silently mangles a row.** Anything the parser had to fix is printed to stderr with the row number, so a
  conversion either reproduces the input faithfully or tells you exactly where it did not.
* **Strings stay strings** unless you ask for `--coerce`. This keeps leading zeros in ZIP codes and invoice numbers intact.
