#!/usr/bin/env python3
"""Install the zig skill from an audited release into a skills directory.

Run it from a checkout of a release tag:

  git clone --depth 1 --branch <tag> https://github.com/zaxified/zig-skills zig-skills
  python3 zig-skills/scripts/install.py --dest ~/.claude/skills/zig          # this machine
  python3 zig-skills/scripts/install.py --dest <repo>/.claude/skills/zig     # a project (also cloud sessions)

Before copying anything it checks, in the checkout it runs from:
  1. HEAD is exactly a v* tag (not a branch tip);
  2. audits/<tag>.md records that tag's content id with "verdict: pass" and
     "approved-by:" (scripts/release.py verify);
  3. the safety gate passes on the content being installed (scripts/audit.py).

The destination gets skills/zig/ plus a .zig-skills-source.json manifest
(tag, commit, content id, file list with sha256). An existing destination is
replaced only if it carries that manifest, and only the files the manifest
lists are removed, so a directory the installer did not create is never
touched.

  scripts/install.py --check DIR    verify an installed copy against its manifest
                                    (for a consumer's CI: nothing edited, nothing added)
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAYLOAD = os.path.join(ROOT, "skills", "zig")
MANIFEST = ".zig-skills-source.json"


def git(*a):
    return subprocess.run(["git", "-C", ROOT, *a], check=True, capture_output=True, text=True).stdout.strip()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def payload_files(base):
    out = []
    for d, dirs, files in os.walk(base):
        dirs.sort()
        for f in sorted(files):
            if f == MANIFEST:
                continue
            p = os.path.join(d, f)
            out.append(os.path.relpath(p, base).replace(os.sep, "/"))
    return out


def fail(msg):
    print(f"install: {msg}", file=sys.stderr)
    return 1


def check(dest):
    mpath = os.path.join(dest, MANIFEST)
    if not os.path.exists(mpath):
        return fail(f"{dest} has no {MANIFEST}; not an installed release")
    with open(mpath, encoding="utf-8") as f:
        m = json.load(f)
    bad = 0
    listed = {e["path"]: e["sha256"] for e in m["files"]}
    for rel in payload_files(dest):
        if rel not in listed:
            print(f"install: extra file not in the release: {rel}", file=sys.stderr)
            bad += 1
        elif sha256(os.path.join(dest, rel)) != listed[rel]:
            print(f"install: modified since install: {rel}", file=sys.stderr)
            bad += 1
    for rel in listed:
        if not os.path.exists(os.path.join(dest, rel)):
            print(f"install: missing: {rel}", file=sys.stderr)
            bad += 1
    print(f"install: {dest} = {m['tag']} ({m['commit'][:12]}): {'OK' if not bad else f'{bad} problem(s)'}", file=sys.stderr)
    return 1 if bad else 0


def remove_previous(dest):
    """Remove only what a previous install recorded, then the empty dirs."""
    with open(os.path.join(dest, MANIFEST), encoding="utf-8") as f:
        m = json.load(f)
    for e in m["files"]:
        p = os.path.join(dest, e["path"])
        if os.path.isfile(p) and not os.path.islink(p):
            os.remove(p)
    os.remove(os.path.join(dest, MANIFEST))
    for d, dirs, files in sorted(os.walk(dest, topdown=False), key=lambda t: -len(t[0])):
        if not os.listdir(d):
            os.rmdir(d)
    if os.path.exists(dest):
        left = payload_files(dest)
        raise SystemExit(f"install: {dest} still holds files the previous release did not install: {left[:5]}; move them away first")


def install(dest, allow_untagged):
    tags = [t for t in git("tag", "--points-at", "HEAD").split() if t.startswith("v")]
    if not tags and not allow_untagged:
        return fail("HEAD is not a v* release tag; clone with --branch <tag>")
    tag = tags[0] if tags else "untagged"
    if tags:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "release.py"), "verify", tag])
        if r.returncode:
            return fail(f"{tag} has no valid audit record; refusing")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "audit.py")], capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        return fail("safety gate fails on this checkout; refusing")

    dest = os.path.abspath(os.path.expanduser(dest))
    if os.path.lexists(dest):
        if os.path.islink(dest) or not os.path.isdir(dest):
            return fail(f"{dest} exists and is not a directory")
        if not os.path.exists(os.path.join(dest, MANIFEST)):
            if os.listdir(dest):
                return fail(f"{dest} exists, is not empty and was not created by this installer; move it away first")
        else:
            remove_previous(dest)

    files = payload_files(PAYLOAD)
    entries = []
    for rel in files:
        src = os.path.join(PAYLOAD, rel)
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        entries.append({"path": rel, "sha256": sha256(dst)})
    cid = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "release.py"), "content-id"],
                         check=True, capture_output=True, text=True).stdout.strip()
    manifest = {
        "repository": "https://github.com/zaxified/zig-skills",
        "tag": tag,
        "commit": git("rev-parse", "HEAD"),
        "content_id": cid,
        "files": entries,
    }
    with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"install: {tag} -> {dest} ({len(entries)} files)", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dest", help="skills directory to install into, e.g. ~/.claude/skills/zig")
    g.add_argument("--check", metavar="DIR", help="verify an installed copy against its manifest")
    ap.add_argument("--allow-untagged", action="store_true", help="development only: install a checkout that is not a release tag")
    a = ap.parse_args()
    if a.check:
        return check(os.path.abspath(os.path.expanduser(a.check)))
    return install(a.dest, a.allow_untagged)


if __name__ == "__main__":
    sys.exit(main())
