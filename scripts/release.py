#!/usr/bin/env python3
"""Tie a release tag to the audit that cleared it.

The audit record audits/<tag>.md cannot name the commit or tree it lives in,
so it names a content id instead: sha256 over the sorted (path, git blob id)
pairs of everything scripts/audit.py audits, i.e. everything a consumer
receives. Changing one published byte changes the id.

  scripts/release.py content-id [REV]    print the content id of REV (default HEAD)
  scripts/release.py verify TAG          fail unless audits/TAG.md at TAG records
                                         TAG's content id and "verdict: pass"
"""
import hashlib
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit import AUDITED_EXTRA, PAYLOAD_DIR  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*a):
    return subprocess.run(["git", "-C", ROOT, *a], check=True, capture_output=True, text=True).stdout


def content_id(rev):
    paths = [PAYLOAD_DIR] + AUDITED_EXTRA
    out = git("ls-tree", "-r", "--full-tree", rev, "--", *paths)
    entries = []
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode, kind, blob = meta.split()
        entries.append(f"{mode} {blob} {path}")
    if not entries:
        raise SystemExit(f"no audited content at {rev}")
    h = hashlib.sha256("\n".join(sorted(entries)).encode()).hexdigest()
    return h, len(entries)


def verify(tag):
    cid, n = content_id(tag)
    try:
        record = git("show", f"{tag}:audits/{tag}.md")
    except subprocess.CalledProcessError:
        print(f"release: {tag} has no audits/{tag}.md", file=sys.stderr)
        return 1
    ok = True
    m = re.search(r"^content-id:\s*([0-9a-f]{64})\s*$", record, re.M)
    if not m or m.group(1) != cid:
        print(f"release: content-id mismatch: record {m.group(1) if m else 'missing'}, tag {cid}", file=sys.stderr)
        ok = False
    if not re.search(r"^verdict:\s*pass\s*$", record, re.M):
        print("release: record has no 'verdict: pass'", file=sys.stderr)
        ok = False
    if not re.search(r"^approved-by:\s*\S+", record, re.M):
        print("release: record has no 'approved-by:' line", file=sys.stderr)
        ok = False
    print(f"release: {tag} content-id {cid} ({n} files): {'OK' if ok else 'FAILED'}", file=sys.stderr)
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "content-id":
        cid, n = content_id(sys.argv[2] if len(sys.argv) > 2 else "HEAD")
        print(cid)
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "verify":
        return verify(sys.argv[2])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
