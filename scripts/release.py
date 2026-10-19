#!/usr/bin/env python3
"""Tie a release tag to the audit that cleared it.

The audit record audits/<tag>.md cannot name the commit or tree it lives in,
so it names a content id instead: sha256 over the sorted (path, git blob id)
pairs of everything scripts/audit.py audits, i.e. everything a consumer
receives. Changing one published byte changes the id.

  scripts/release.py content-id [REV]    print the content id of REV (default HEAD)
  scripts/release.py verify TAG          fail unless audits/TAG.md at TAG records
                                         TAG's content id and "verdict: pass"
  scripts/release.py ci-status [REV]     fail unless the `gate` workflow (safety gate +
                                         SkillSpector) passed on REV's commit on GitHub
                                         and no gate run on it failed or is still running
  scripts/release.py tag TAG             create the annotated tag TAG at HEAD, only if the
                                         tree is clean, HEAD is origin/main, audits/TAG.md
                                         at HEAD records HEAD's content id, verdict and
                                         sign-off, and ci-status passes on HEAD. It does
                                         not push; the maintainer pushes the tag.

Why `tag` exists: SkillSpector runs only in CI, and tags are protected (they
cannot be moved). Cutting the tag together with the push let a scanner finding
arrive after the tag existed, which burned the version twice (r2 -> r3,
r4 -> r5). The order is now enforced: commit the audit record, push main, wait
for the gate, then `tag`, then push the tag.
"""
import hashlib
import json
import os
import shutil
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit import AUDITED_EXTRA, PAYLOAD_DIR  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "zaxified/zig-skills"
GATE_WORKFLOW = "gate"


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


def verify(tag, rev=None):
    rev = rev or tag
    cid, n = content_id(rev)
    try:
        record = git("show", f"{rev}:audits/{tag}.md")
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
    m = re.search(r"^approved-by:\s*(\S.*?)\s*$", record, re.M)
    if not m or re.fullmatch(r"(?i)pending|tbd|todo|none|-|<.*>", m.group(1)):
        print("release: record is not signed off ('approved-by:' missing or a placeholder)", file=sys.stderr)
        ok = False
    print(f"release: {tag} content-id {cid} ({n} files): {'OK' if ok else 'FAILED'}", file=sys.stderr)
    return 0 if ok else 1


def gate_runs(sha):
    """The `gate` workflow runs GitHub has for commit sha (any branch or tag)."""
    path = f"repos/{REPO}/actions/runs?head_sha={sha}&per_page=100"
    if shutil.which("gh"):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
        if r.returncode == 0:
            data = json.loads(r.stdout)
        else:
            raise SystemExit(f"release: gh api failed: {r.stderr.strip()}")
    else:
        import urllib.request
        req = urllib.request.Request(f"https://api.github.com/{path}",
                                     headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as f:
            data = json.load(f)
    return [r for r in data.get("workflow_runs", []) if r.get("name") == GATE_WORKFLOW]


def ci_verdict(runs):
    """(ok, reason) for a list of gate runs on one commit.

    Passes only if at least one run succeeded and every run has finished
    without failing: a red tag run (the scanner on the tag push) condemns the
    commit even when its main run was green.
    """
    if not runs:
        return False, "no gate run on this commit (pushed? CI started?)"
    pending = [r for r in runs if r.get("status") != "completed"]
    if pending:
        return False, f"{len(pending)} gate run(s) still {pending[0].get('status')}; wait"
    bad = [r for r in runs if r.get("conclusion") != "success"]
    if bad:
        b = bad[0]
        return False, f"gate run {b.get('id')} on {b.get('head_branch')} concluded {b.get('conclusion')}"
    return True, f"{len(runs)} gate run(s), all success"


def ci_status(rev):
    sha = git("rev-parse", f"{rev}^{{commit}}").strip()
    ok, why = ci_verdict(gate_runs(sha))
    print(f"release: CI on {sha[:12]}: {'OK' if ok else 'NOT OK'} ({why})", file=sys.stderr)
    return 0 if ok else 1


def tag(name):
    if not re.fullmatch(r"v\d+\.\d+\.\d+-r\d+", name):
        print(f"release: {name!r} is not a vX.Y.Z-rN tag", file=sys.stderr)
        return 1
    if git("status", "--porcelain").strip():
        print("release: working tree is not clean", file=sys.stderr)
        return 1
    if git("tag", "--list", name).strip():
        print(f"release: tag {name} already exists (tags are protected; take the next number)", file=sys.stderr)
        return 1
    git("fetch", "-q", "origin", "main")
    head = git("rev-parse", "HEAD").strip()
    if head != git("rev-parse", "origin/main").strip():
        print("release: HEAD is not origin/main; push main and let the gate run first", file=sys.stderr)
        return 1
    if verify(name, "HEAD"):
        return 1
    if ci_status("HEAD"):
        return 1
    git("tag", "-a", name, "-m", f"zig-skills {name}")
    print(f"release: tagged {name} at {head[:12]}; push it with: git push origin {name}", file=sys.stderr)
    return 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "content-id":
        cid, n = content_id(sys.argv[2] if len(sys.argv) > 2 else "HEAD")
        print(cid)
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "verify":
        return verify(sys.argv[2])
    if len(sys.argv) in (2, 3) and sys.argv[1] == "ci-status":
        return ci_status(sys.argv[2] if len(sys.argv) > 2 else "HEAD")
    if len(sys.argv) == 3 and sys.argv[1] == "tag":
        return tag(sys.argv[2])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
