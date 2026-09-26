#!/usr/bin/env python3
"""Scan every blob ever committed for secrets.

A push publishes the whole history, not just the tip, so a key removed in a
later commit is still public. Uses the gate's SECRET patterns, with one
difference: a private key counts only when its BEGIN line is followed by key
material. The gate's own tests plant a bare BEGIN line to prove the gate
catches it, and those test files are in the history too.

Usage: scripts/scan-history.py   (exit 1 on any finding)
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit import SECRET  # noqa: E402

PRIVATE_KEY_WITH_BODY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*\n\s*[A-Za-z0-9+/=]{40,}")


def main():
    objs = subprocess.run(["git", "rev-list", "--objects", "--all"], capture_output=True, text=True, check=True).stdout
    kinds = subprocess.run(["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                           input="\n".join(l.split()[0] for l in objs.splitlines()),
                           capture_output=True, text=True, check=True).stdout
    blobs = {l.split()[0] for l in kinds.splitlines() if l.endswith(" blob")}
    names = {l.split()[0]: (l[41:] if len(l) > 41 else "") for l in objs.splitlines()}
    bad = 0
    for sha in sorted(blobs):
        data = subprocess.run(["git", "cat-file", "-p", sha], capture_output=True).stdout.decode("utf-8", "replace")
        for pat, msg in SECRET:
            if "PRIVATE KEY" in pat:
                if PRIVATE_KEY_WITH_BODY.search(data):
                    print(f"{msg} in blob {sha} ({names.get(sha, '')})")
                    bad += 1
            elif re.search(pat, data):
                print(f"{msg} in blob {sha} ({names.get(sha, '')})")
                bad += 1
    print(f"{len(blobs)} blobs scanned, {bad} finding(s)", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
