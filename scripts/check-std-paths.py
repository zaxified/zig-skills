#!/usr/bin/env python3
"""Check that every `std.a.b.c` path used in the skill's Zig examples exists
in the installed Zig standard library.

Most examples are fragments that cannot be compiled on their own, but the way
they go stale is almost always the same: a std declaration is renamed, moved
or removed. This resolves each path one segment at a time with @hasDecl /
@hasField, so one compile reports every missing path at once.

Blocks that show a deliberately wrong pattern are skipped: a block containing
WRONG, BAD, "compile error", "removed" or "0.15" markers, and any block whose
nearest preceding heading or line says so.

Usage: scripts/check-std-paths.py [--zig zig] [--list]
Exit status 1 if any path does not resolve.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "zig")

BLOCK = re.compile(r"```zig\n(.*?)```", re.S)
# std.<ident>(.<ident>)* — stops at a call, index, or anything that is not a name.
PATH = re.compile(r"(?<![\w.])std((?:\.(?:[A-Za-z_]\w*|@\"[^\"]+\"))+)")
BAD_MARK = re.compile(
    r"WRONG|\bBAD\b|compile error|❌|removed|REMOVED|0\.1[45]|old API|deprecated|Before|OLD",
)
# A line that marks everything after it inside the block as wrong / correct.
# Section markers count only at the start of a comment ("// WRONG (0.15)",
# "// Before:"). Anywhere in the comment, a word like "before" in ordinary
# prose silently switched off checking for the rest of the block.
WRONG_LINE = re.compile(r"^\s*//+\s*(?:[-*(\[]\s*)?(WRONG|BAD\b|❌|OLD\b|Old\b|Before\b|0\.1[45]\b|Removed\b|removed\b|Deprecated\b)")
RIGHT_LINE = re.compile(r"^\s*//+\s*(?:[-*(\[]\s*)?(CORRECT|GOOD\b|✅|0\.16\b|New\b|After\b|Now\b)")
# Paths that only exist on another OS, target or behind a build option.
IGNORE = re.compile(r"^(os\.windows|os\.wasi|os\.uefi|os\.plan9|Target\.\w+\.cpu)")


# A whole section can be old code: "## TCP Server (0.15.x, removed in 0.16)".
# Only an explicit word inside the heading's parentheses counts: a bare
# "(0.15.x)" in this skill usually means "introduced in 0.15, still valid".
OLD_HEADING = re.compile(r"^#{1,6}\s.*\(\s*0\.1[45][^)]*\bremoved\b[^)]*\)|^#{1,6}\s.*\(\s*deprecated\s*\)|^#{1,6}\s+Old API\b", re.I)


def in_old_section(text, pos):
    """True if any heading enclosing pos (nearest one per level) marks it as old code."""
    level = 7
    for line in reversed(text[:pos].split("\n")):
        m = re.match(r"^(#{1,6})\s", line)
        if m and len(m.group(1)) < level:
            if OLD_HEADING.match(line):
                return True
            level = len(m.group(1))
            if level == 1:
                break
    return False


def skip_block(text, m):
    before = text[: m.start()].rstrip("\n").split("\n")[-1]
    return bool(BAD_MARK.search(before)) or in_old_section(text, m.start())


def usable_lines(block):
    """Lines of a block not inside a WRONG section (sections toggle per comment)."""
    ok = True
    for line in block.splitlines():
        if WRONG_LINE.search(line):
            ok = False
        elif RIGHT_LINE.search(line):
            ok = True
        if ok:
            yield line


# In 0.16 std.Io.File and std.Io.net.Stream take the Io instance first:
# file.reader(io, &buf). A one-argument call is the 0.15 form. The HTTP
# client's response.reader(&buf) really takes one argument.
ONE_ARG_RW = re.compile(r"\b(?!response\b|resp\b|req\b|request\b)[\w\])]+(?:\(\))?\.(reader|writer)\(\s*&?\w+(?:\[[^\]]*\])?\s*\)")


# std.Io.File and std.Io.Dir methods take the Io instance first in 0.16
# (checked against lib/std/Io/File.zig and Io/Dir.zig; iterate/walk do not).
# Receivers are recognised by name, so this sees fragments the compile check
# cannot. File.read/write/writeAll/readToEndAlloc and friends no longer exist.
_IO_METHODS = (
    "access close createDir createDirPath createDirPathOpen createFile deleteDir deleteFile "
    "deleteTree openDir openFile readFile readLink realPath realPathFile realPathFileAlloc "
    "setOwner setPermissions stat statFile writeFile createMemoryMap isTty length lock "
    "readPositional readPositionalAll readStreaming setLength setTimestamps sync tryLock "
    "unlock writePositional writePositionalAll writeStreaming writeStreamingAll"
).split()
_GONE = "read write writeAll readAll readToEndAlloc readToEndAllocOptions pread pwrite getEndPos seekTo seekBy getPos".split()
_RECV = (r"(?:\b(?:file|f|dir|d|fd|handle|tmp_dir|tmp\.dir|src|dst|in_file|out_file|\w+_file|\w+_dir)"
         r"|cwd\(\)|stdout\(\)|stderr\(\)|stdin\(\))")
IO_ARITY = re.compile(_RECV + r"\.(" + "|".join(_IO_METHODS) + r")\(\s*(?!io\b)(?:[^)\s]|\))")
FILE_GONE = re.compile(_RECV + r"\.(" + "|".join(_GONE) + r")\(")


def arity_findings():
    out = []
    for f in sorted(glob.glob(os.path.join(SKILL, "**", "*.md"), recursive=True)):
        text = open(f, encoding="utf-8").read()
        for m in BLOCK.finditer(text):
            if skip_block(text, m):
                continue
            line0 = text.count("\n", 0, m.start()) + 2
            for line in usable_lines(m.group(1)):
                code = line.split("//")[0]
                where = f"{os.path.relpath(f, ROOT)}:{line0}"
                if ONE_ARG_RW.search(code):
                    out.append(f"{where}: 0.15-style one-argument reader/writer: {line.strip()[:80]}")
                elif IO_ARITY.search(code):
                    out.append(f"{where}: File/Dir method without io: {line.strip()[:80]}")
                elif FILE_GONE.search(code):
                    out.append(f"{where}: File method that no longer exists in 0.16: {line.strip()[:80]}")
    return out


def collect():
    found = {}  # path -> first "file:line"
    for f in sorted(glob.glob(os.path.join(SKILL, "**", "*.md"), recursive=True)):
        text = open(f, encoding="utf-8").read()
        for m in BLOCK.finditer(text):
            if skip_block(text, m):
                continue
            line0 = text.count("\n", 0, m.start()) + 2
            for line in usable_lines(m.group(1)):
                if line.lstrip().startswith("//"):
                    continue
                for p in PATH.finditer(line.split("//")[0]):
                    segs = re.findall(r'[A-Za-z_]\w*|@"[^"]+"', p.group(1))
                    path = ".".join(segs)
                    if IGNORE.match(path):
                        continue
                    found.setdefault(path, f"{os.path.relpath(f, ROOT)}:{line0}")
    return found


ZIG_PRELUDE = r"""const std = @import("std");

fn isContainer(T: type) bool {
    return switch (@typeInfo(T)) {
        .@"struct", .@"union", .@"enum", .@"opaque" => true,
        else => false,
    };
}

/// Walks `std.<names...>`; returns the first segment that does not exist, or
/// null. Descends through declarations, through types of namespace values and
/// through struct/union field types; stops (as found) at anything else, such
/// as a function or an enum tag, since a path cannot usefully continue there.
fn missing(comptime names: []const []const u8) ?[]const u8 {
    comptime {
        @setEvalBranchQuota(1_000_000);
        var cur: type = std;
        for (names, 0..) |n, i| {
            if (!isContainer(cur)) return null;
            const found = @hasDecl(cur, n) or @hasField(cur, n);
            if (!found) return n;
            // The last segment only has to exist. Evaluating it would pull in
            // whatever it depends on (libc, the test runner, another OS).
            if (i == names.len - 1) return null;
            if (@hasDecl(cur, n)) {
                const v = @field(cur, n);
                if (@TypeOf(v) == type) cur = v else cur = @TypeOf(v);
            } else {
                if (@typeInfo(cur) == .@"enum") return null;
                cur = @FieldType(cur, n);
            }
        }
        return null;
    }
}
"""


def zig_source(paths):
    out = [ZIG_PRELUDE]
    for path in sorted(paths):
        names = ", ".join('"%s"' % s.removeprefix('@"').removesuffix('"') for s in path.split("."))
        out.append(
            f'comptime {{ if (missing(&.{{ {names} }})) |n| @compileError("missing: std.{path} (at ." ++ n ++ ")"); }}'
        )
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zig", default="zig")
    ap.add_argument("--list", action="store_true", help="print the collected paths and exit")
    args = ap.parse_args()

    found = collect()
    if args.list:
        for p, where in sorted(found.items()):
            print(f"std.{p}\t{where}")
        return 0

    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "paths.zig")
        open(src, "w").write(zig_source(found))
        r = subprocess.run(
            [args.zig, "test", "-lc", "-fno-emit-bin", src, "--cache-dir", os.path.join(d, "c"),
             "--global-cache-dir", os.path.join(d, "g")],
            capture_output=True, text=True,
        )
    missing = sorted(set(re.findall(r"missing: std\.([\w.@\"]+)", r.stderr)))
    for p in missing:
        print(f"std.{p}\t{found.get(p, '?')}")
    other = [l for l in r.stderr.splitlines() if "error:" in l and "missing: std." not in l]
    for l in other:
        print(l, file=sys.stderr)
    arity = arity_findings()
    for a in arity:
        print(a)
    print(f"{len(found)} paths checked, {len(missing)} missing, {len(other)} other errors, {len(arity)} arity", file=sys.stderr)
    return 1 if missing or other or arity else 0


if __name__ == "__main__":
    sys.exit(main())
