#!/usr/bin/env python3
"""Keep the CI itself from becoming the way in.

Every workflow must: pin each `uses:` to a full commit SHA, declare
top-level `permissions:` and never grant write, avoid pull_request_target
and workflow_run (they run with the base repository's secrets on untrusted
code), and never interpolate ${{ github.event.* }} or head_ref into a
`run:` script (shell injection through a branch name or PR title).

Usage: scripts/check-workflows.py   (exit 1 on any finding)
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(path, text):
    out = []
    rel = os.path.relpath(path, ROOT)
    if not re.search(r"^permissions:\s*$|^permissions:\s*\S", text, re.M):
        out.append(f"{rel}: no top-level permissions:")
    if re.search(r"^\s+\w[\w-]*:\s*write\b|^permissions:\s*write-all", text, re.M):
        out.append(f"{rel}: grants write permission")
    if re.search(r"\bpull_request_target\b|\bworkflow_run\b", text):
        out.append(f"{rel}: pull_request_target / workflow_run")
    for n, line in enumerate(text.splitlines(), 1):
        m = re.search(r"\buses:\s*([^\s#]+)", line)
        if m and not m.group(1).startswith("./") and not re.search(r"@[0-9a-f]{40}$", m.group(1)):
            out.append(f"{rel}:{n}: action not pinned to a commit SHA: {m.group(1)}")
        if re.search(r"\$\{\{\s*github\.(event|head_ref)", line):
            out.append(f"{rel}:{n}: untrusted github.event/head_ref expression")
    return out


def main():
    findings = []
    files = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.y*ml")))
    for p in files:
        with open(p, encoding="utf-8") as f:
            findings += check(p, f.read())
    for x in findings:
        print(x)
    print(f"{len(files)} workflow(s), {len(findings)} finding(s)", file=sys.stderr)
    return 1 if findings or not files else 0


if __name__ == "__main__":
    sys.exit(main())
