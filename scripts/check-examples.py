#!/usr/bin/env python3
"""Compile every self-contained Zig example against the installed Zig.

check-std-paths.py proves the std names exist; it cannot see a wrong field
name, a missing argument or a changed return type. This compiles every
```zig block that stands on its own: it imports std and has `pub fn main`
(built as an executable) or a top-level `test` (built as a test), and is not
marked as wrong code (same markers as check-std-paths.py). Semantic analysis
only (-fno-emit-bin), linked against libc so std.c references resolve.

A self-contained-looking block that is deliberately incomplete (it reads a
file from the reader's project, say) opts out with a first line
`// not standalone: <reason>`.

Usage: scripts/check-examples.py [--zig zig] [--list]
Exit status 1 if any block fails to compile.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("paths", os.path.join(HERE, "check-std-paths.py"))
paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paths)

OPT_OUT = re.compile(r"^\s*//\s*not standalone:\s*\S{3,}")


def blocks():
    for f in sorted(glob.glob(os.path.join(paths.SKILL, "**", "*.md"), recursive=True)):
        text = open(f, encoding="utf-8").read()
        for m in paths.BLOCK.finditer(text):
            b = m.group(1)
            before = text[: m.start()].rstrip("\n").split("\n")[-1]
            if paths.BAD_MARK.search(before) or paths.WRONG_LINE.search(b):
                continue
            if '@import("std")' not in b:
                continue
            kind = "exe" if re.search(r"pub fn main\(", b) else ("test" if re.search(r"^test\b", b, re.M) else None)
            if not kind:
                continue
            where = f"{os.path.relpath(f, ROOT)}:{text.count(chr(10), 0, m.start()) + 2}"
            if OPT_OUT.match(b.split("\n", 1)[0]):
                continue
            yield where, kind, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zig", default="zig")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    found = list(blocks())
    if a.list:
        for where, kind, _ in found:
            print(where, kind)
        return 0
    failed = 0
    with tempfile.TemporaryDirectory() as d:
        for i, (where, kind, b) in enumerate(found):
            src = os.path.join(d, f"ex{i}.zig")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(b)
            cmd = [a.zig, "build-exe" if kind == "exe" else "test", "-fno-emit-bin", "-lc", src,
                   "--cache-dir", os.path.join(d, "c"), "--global-cache-dir", os.path.join(d, "g")]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode:
                failed += 1
                errs = [l.split("error:", 1)[1].strip() for l in r.stderr.splitlines() if "error:" in l]
                print(f"{where}: [{kind}] {errs[0] if errs else r.stderr.strip()[:200]}")
    print(f"{len(found)} standalone example(s), {failed} failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
