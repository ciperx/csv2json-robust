import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPT = HERE / "csv2json.py"


def run(args, stdin=None):
    return subprocess.run([sys.executable, str(SCRIPT)] + args, input=stdin,
                          capture_output=True, text=True)


def test_basic_comma(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("name,age\nalice,30\nbob,41\n")
    r = run([str(f), "--indent", "0"])
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [{"name": "alice", "age": "30"}, {"name": "bob", "age": "41"}]


def test_semicolon_autodetect(tmp_path):
    f = tmp_path / "b.csv"
    f.write_text("a;b;c\n1;2;3\n")
    r = run([str(f), "--indent", "0"])
    assert json.loads(r.stdout) == [{"a": "1", "b": "2", "c": "3"}]


def test_quoted_delimiter_and_newline(tmp_path):
    f = tmp_path / "c.csv"
    f.write_text('id,note\n1,"hello, world"\n2,"two\nlines"\n')
    r = run([str(f), "--indent", "0"])
    data = json.loads(r.stdout)
    assert data[0]["note"] == "hello, world"
    assert data[1]["note"] == "two\nlines"


def test_escaped_quotes_and_unicode(tmp_path):
    f = tmp_path / "d.csv"
    f.write_text('id,quote\n1,"she said ""hi"""\n2,café\n', encoding="utf-8")
    r = run([str(f), "--indent", "0"])
    data = json.loads(r.stdout)
    assert data[0]["quote"] == 'she said "hi"'
    assert data[1]["quote"] == "café"


def test_duplicate_and_blank_headers(tmp_path):
    f = tmp_path / "e.csv"
    f.write_text("id,,id\n1,x,2\n")
    r = run([str(f), "--indent", "0"])
    data = json.loads(r.stdout)
    assert list(data[0].keys()) == ["id", "column_2", "id_2"]
    assert data[0]["id_2"] == "2"
    assert "duplicate header" in r.stderr


def test_ragged_rows_are_padded_not_dropped(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("a,b,c\n1,2\n1,2,3,4\n")
    r = run([str(f), "--indent", "0"])
    data = json.loads(r.stdout)
    assert data[0] == {"a": "1", "b": "2", "c": None} or data[0]["c"] == ""
    assert "extra fields dropped" in r.stderr


def test_coerce_scalars(tmp_path):
    f = tmp_path / "g.csv"
    f.write_text("n,x,b,e\n42,3.5,true,\n")
    r = run([str(f), "--coerce", "--indent", "0"])
    assert json.loads(r.stdout) == [{"n": 42, "x": 3.5, "b": True, "e": None}]


def test_bom_encoding(tmp_path):
    f = tmp_path / "h.csv"
    f.write_bytes("id,val\n1,ok\n".encode("utf-8-sig"))
    r = run([str(f), "--indent", "0"])
    assert json.loads(r.stdout) == [{"id": "1", "val": "ok"}]


def test_stream_mode(tmp_path):
    f = tmp_path / "i.csv"
    f.write_text("a,b\n1,2\n3,4\n")
    out = tmp_path / "out.jsonl"
    r = run([str(f), "--stream", "-o", str(out)])
    assert r.returncode == 0, r.stderr
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    assert lines == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]


def test_stdin(tmp_path):
    r = run(["-", "--indent", "0"], stdin="x,y\n1,2\n")
    assert json.loads(r.stdout) == [{"x": "1", "y": "2"}]


def test_missing_file_is_clean_error():
    r = run(["/nonexistent/file.csv"])
    assert r.returncode == 2
    assert "not found" in r.stderr
