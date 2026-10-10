#!/usr/bin/env python3
"""Check that the skill's correct examples use no std name that the installed
Zig standard library marks as deprecated or removed.

check-std-paths.py proves a name still exists. A deprecated alias still
exists, so it passes there, and the skill would go on teaching a spelling
that the next release deletes. The std marks these consistently: a doc
comment that says "Deprecated", or a declaration that is now
`@compileError(...)`. The table is read from the std of the Zig given with
--zig, so it follows every upgrade without being edited by hand.

A name is reported in two forms:
  - qualified, `std.<module>.<name>`, when the name is a top-level
    declaration of that module's file (std.fmt.allocPrint, std.builtin);
  - as a member, `.name` or `@name`, only when no non-deprecated public
    declaration anywhere in std has the same name (`.getLastOrNull(`,
    `.ReleaseFast`), since a receiver's type cannot be resolved from text.

A short table of language changes (removed syntax, builtins) that no std
file shows is checked the same way.

Blocks and lines marked as wrong code are skipped exactly as in
check-std-paths.py.

Usage: scripts/check-deprecated.py [--zig zig] [--list]
Exit status 1 if any correct example uses a deprecated name.
"""
import argparse
import collections
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("paths", os.path.join(HERE, "check-std-paths.py"))
paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paths)

DECL = re.compile(r"^(\s*)pub (?:const|fn|var) ([A-Za-z_]\w*)\b(.*)")
# The decl itself is deprecated, not a field default or a parameter it mentions.
DEPRECATED_DOC = re.compile(r"(?:^|[.!]\s)Deprecated\b|\bdeprecated in favor\b|\bdeprecated;", re.I)
NOT_ABOUT_DECL = re.compile(r"Default initialization", re.I)
# Guards such as `std.testing.allocator = ... else @compileError("not testing")`.
GUARD = re.compile(r'@compileError\("not testing"\)')
REMOVED = re.compile(r"\s*(?::[^=]*)?=\s*@compileError\(")


def std_dir(zig):
    out = subprocess.run([zig, "env"], capture_output=True, text=True, check=True).stdout
    m = re.search(r'\.std_dir\s*=\s*"([^"]+)"', out) or re.search(r'"std_dir"\s*:\s*"([^"]+)"', out)
    if not m:
        sys.exit("cannot find std_dir in `zig env`")
    return m.group(1)


def module_of(std, f):
    """lib/std/Io/Dir.zig -> "Io.Dir"; lib/std/std.zig -> ""."""
    rel = os.path.relpath(f, std)[: -len(".zig")]
    return "" if rel == "std" else rel.replace(os.sep, ".")


def scan_std(std):
    """(qualified, member, alive): qualified[(module, name)] and member[name] map to a note;
    alive is every public name that has at least one non-deprecated declaration."""
    qualified, member, alive = {}, {}, set()
    for f in glob.glob(os.path.join(std, "**", "*.zig"), recursive=True):
        with open(f, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
        mod = module_of(std, f)
        for i, line in enumerate(lines):
            m = DECL.match(line)
            if not m:
                continue
            indent, name, rest = m.groups()
            doc, j = [], i - 1
            while j >= 0 and lines[j].strip().startswith("///"):
                doc.insert(0, lines[j].strip()[3:].strip())
                j -= 1
            text = " ".join(doc)
            # Removed: the whole declaration is a compile error. A @compileError inside
            # an expression (`orelse @compileError(...)`, a return type) is not.
            removed = bool(REMOVED.match(rest)) and not GUARD.search(rest)
            deprecated = DEPRECATED_DOC.search(text) and not NOT_ABOUT_DECL.search(text)
            if not (removed or deprecated):
                alive.add(name)
                continue
            note = ("removed: " + rest.strip()[:100]) if removed else text[:100]
            where = f"{os.path.relpath(f, std)}:{i + 1}"
            if not indent:
                qualified[(mod, name)] = (note, where)
            # A member of a value: a nested declaration, or a top-level one of a file
            # that is itself a type (Io/Dir.zig, Build/Step/Run.zig). A top-level name
            # of a namespace file (std.builtin, fs/path.zig's relative) is only ever
            # reached qualified.
            if indent or os.path.basename(f)[:1].isupper():
                member.setdefault(name, (note, where))
    member = {n: v for n, v in member.items() if n not in alive}
    return qualified, member


QUALIFIED = re.compile(r"(?<![\w.])std((?:\.[A-Za-z_]\w*)+)")
# `.name` or `@name`, but not the end of a range (`buf[0..len]`).
MEMBER = re.compile(r"(?<!\.)[.@]([A-Za-z_]\w*)")

# Language changes of 0.17.0 that the std source cannot show (release notes,
# "Language Changes"). Each was confirmed by compiling it on 0.17.0.
LANGUAGE = [
    (re.compile(r"[}\]]\s*\*\*\s*[\w(]|\"\s*\*\*\s*\d"), "array repetition `**` was removed; use @splat"),
    (re.compile(r"\berrdefer\s*\|"), "`errdefer |err|` capture was removed; catch in a wrapper function"),
    (re.compile(r"\bvoid\{\}"), "`void{}` was removed; use `{}`"),
    (re.compile(r"(?<![\w.])i0\b"), "`i0` was removed; use `u0`"),
    (re.compile(r"@cImport\b"), "@cImport was removed; use the translate-c package"),
    (re.compile(r"@Type\("), "@Type was removed (already in 0.16); use @Int, @Struct, @Union, @Enum, @Pointer, @Fn, @Tuple"),
    (re.compile(r"@(intFromEnum|enumFromInt)\b"), "deprecated; use @backingInt / @fromBackingInt"),
    # std.lang.Type is struct-of-arrays in 0.17 for struct, union, enum, fn, opaque and
    # error sets, and Pointer/Fn flags moved into `attrs` (diffed field by field, 0.16 vs 0.17).
    (re.compile(r'@"(?:struct|union|enum)"\.fields\b'), "type info is struct-of-arrays: field_names, field_types/field_values, field_attrs"),
    (re.compile(r'(?:@"(?:struct|union|enum|opaque)"|\binfo)\.decls\b'), "type info has decl_names instead of decls"),
    (re.compile(r"\.(?:is_exhaustive|is_var_args|calling_convention|is_allowzero|is_volatile|address_space)\b"),
     "type info: enum .mode, fn .attrs.varargs / .attrs.@\"callconv\", pointer .attrs.@\"allowzero\"/@\"volatile\"/@\"addrspace\""),
    (re.compile(r'@"fn"\.params\b|\.pointer\.(?:is_const|alignment)\b'), "type info: fn param_types/param_attrs, pointer .attrs.@\"const\"/@\"align\""),
    (re.compile(r"\.linkage\s*=\s*\.(?:internal|link_once)\b"), "GlobalLinkage .internal and .link_once were removed"),
    # @import("builtin") is generated, not in the std tree: its cpu/os/abi/object_format
    # shortcuts are deprecated in 0.17.0 (removed in 0.18.0).
    (re.compile(r"(?<!std\.)\bbuiltin\.(?:cpu|os|abi|object_format)\b"), "deprecated; use builtin.target.cpu / .os / .abi / .ofmt"),
    (re.compile(r"\bb\.(?:args|build_root)\b"), "b.args is gone (run.addPassthruArgs()); b.build_root is b.root"),
]


def line_hit(code, qualified, member):
    """(name, note) of the first deprecated or removed use in one line of code, or None."""
    for rx, note in LANGUAGE:
        m = rx.search(code)
        if m:
            return m.group(0).strip(), ("language", note)
    for q in QUALIFIED.finditer(code):
        segs = q.group(1)[1:].split(".")
        for k in range(len(segs)):
            key = (".".join(segs[:k]), segs[k])
            if key in qualified:
                return "std." + ".".join(segs[: k + 1]), qualified[key]
    for mm in MEMBER.finditer(code):
        if mm.group(1) in member:
            return mm.group(0), member[mm.group(1)]
    return None


def findings(qualified, member):
    out = []
    for f in sorted(glob.glob(os.path.join(paths.SKILL, "**", "*.md"), recursive=True)):
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        for m in paths.BLOCK.finditer(text):
            if paths.skip_block(text, m):
                continue
            line0 = text.count("\n", 0, m.start()) + 2
            for line in paths.usable_lines(m.group(1)):
                hit = line_hit(line.split("//")[0], qualified, member)
                if hit:
                    name, (note, std_where) = hit
                    out.append(f"{os.path.relpath(f, ROOT)}:{line0}: {name} ({std_where}: {note}) :: {line.strip()[:70]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zig", default="zig")
    ap.add_argument("--list", action="store_true", help="print the deprecated-name table and exit")
    a = ap.parse_args()
    qualified, member = scan_std(std_dir(a.zig))
    if a.list:
        for (mod, name), (note, where) in sorted(qualified.items()):
            print(f"std.{mod + '.' if mod else ''}{name}\t{where}\t{note}")
        for name, (note, where) in sorted(member.items()):
            print(f".{name}\t{where}\t{note}")
        return 0
    out = findings(qualified, member)
    for o in out:
        print(o)
    print(f"{len(qualified)} qualified + {len(member)} member names, {len(out)} use(s) in correct code", file=sys.stderr)
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
