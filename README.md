# zig-skills

[![gate](https://github.com/zaxified/zig-skills/actions/workflows/gate.yml/badge.svg)](https://github.com/zaxified/zig-skills/actions/workflows/gate.yml) [![Zig 0.16.0](https://img.shields.io/badge/Zig-0.16.0-f7a41d)](https://ziglang.org/download/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Scanned by NVIDIA SkillSpector](https://img.shields.io/badge/scanned_by-NVIDIA_SkillSpector-76b900)](https://github.com/NVIDIA/SkillSpector) [![Audited releases](https://img.shields.io/badge/releases-audited-2ea44f)](audits/) [![Latest release](https://img.shields.io/github/v/tag/zaxified/zig-skills)](https://github.com/zaxified/zig-skills/tags)

An agent skill for **Zig 0.16.0**: the current std and build-system APIs, migration notes
from 0.14/0.15, and gotchas found in production code. Every release is audited so that
nothing in it can turn against the agent, or the person, using it.

Most model training data predates the 0.15 I/O rewrite and the 0.16 `std.Io` redesign, so
models confidently write `std.io.getStdOut()`, `std.time.timestamp()`, `std.Thread.Mutex`
or managed `ArrayList` calls that no longer compile. The skill tells the agent what changed
and what the 0.16 code looks like, and every `std.*` path used in its correct examples is
checked against the released 0.16.0 standard library in CI.

## What is in it

- `skills/zig/SKILL.md`: breaking changes with WRONG/CORRECT examples, the 0.16 `std.Io`
  model, build system migration, container initialization, a quick-fix table for common
  compile errors, and an index of the references.
- `skills/zig/references/`: one file per std module or topic (ArrayList, HashMap, Io, net,
  http, json, crypto, process, build, testing and fuzzing, comptime, C interop, SIMD,
  data-oriented design, quality tooling), a code-review checklist, and
  `zig-016-gotchas.md`: traps that compile cleanly and are wrong, each confirmed on 0.16.0.

## Why you can trust a release

A skill is not documentation a person skims; it is instructions an agent carries out with
your permissions. So a release has to clear five independent checks:

1. **Safety gate** (`scripts/audit.py`, CI and pre-push). The published content must be
   plain Markdown with no executable parts and no manifest keys that grant execution
   (hooks, allowed tools, MCP servers, remote plugin sources). It is scanned for invisible
   or direction-changing Unicode, HTML comments and other hidden text, images, URLs off an
   allowlist or carrying query strings, destructive or system-altering commands (in shell
   and in Zig argv arrays alike), text addressed to the agent instead of about Zig,
   secrets, encoded blobs, and unsafe advice. A legitimate hit is accepted only by an entry
   in `audit/allow.txt` tied to the hash of that exact line, with a reason. Every rule is
   proven by a planted sample in `tests/`.
2. **An independent scanner.** CI also runs NVIDIA's
   [SkillSpector](https://github.com/NVIDIA/SkillSpector) (static analysis, no model calls,
   no credentials in its environment), installed at a vetted commit with dependencies from
   its lockfile. Every finding it reports is either fixed or listed in
   `audit/skillspector-baseline.yaml` with the exact matched text and the reason it is
   harmless; any other finding fails the build. Workflows are checked by
   [zizmor](https://github.com/zizmorcore/zizmor) and
   [actionlint](https://github.com/rhysd/actionlint), each pinned by digest or checksum.
3. **Correctness check** (`scripts/check-std-paths.py`, CI). Every `std.a.b.c` path in the
   correct examples must exist in the Zig 0.16.0 standard library.
4. **Review of the change.** A reviewer model with read-only tools goes through the diff
   since the last release against a fixed checklist (`audit/REVIEW.md`). Its report is
   advisory, because the content under review can try to influence it; the deterministic
   gate decides.
5. **A person signs off.** `audits/<tag>.md` records the release's content id (sha256 over
   every published file), the review, `verdict: pass` and `approved-by:`. CI refuses a tag
   whose record is missing or does not match the tagged content byte for byte.

Content taken from upstream goes through the same checks as our own.

## Install

Install from a release tag, never from `main`:

```bash
git clone --depth 1 --branch <tag> https://github.com/zaxified/zig-skills zig-skills
python3 zig-skills/scripts/install.py --dest <skills-dir>/zig
```

`<skills-dir>` is your agent's skills directory: the user-level one for this machine, or
a repository's own `.claude/skills` to make the skill travel with the repository, which is
the way to have it in cloud sessions too.

The installer refuses a checkout that is not a release tag, whose audit record does not
verify, or on which the safety gate fails. It writes `.zig-skills-source.json` next to the
skill, and replaces an existing destination only if that manifest is there, removing only
the files it lists. To check that an installed copy is untouched, for example in a
consumer's CI:

```bash
python3 zig-skills/scripts/install.py --check <skills-dir>/zig
```

As a Claude Code plugin, pinned to a release:

```bash
claude plugin marketplace add zaxified/zig-skills#<tag>
claude plugin install zig-skills@zig-skills
```

## Provenance and license

Built on [nzrsky/zig-skills](https://github.com/nzrsky/zig-skills) (MIT), whose history this
repository keeps. Since then: compile-verified 0.16.0 corrections, the gotchas reference,
the safety gate and the release audit. The upstream `main` targets 0.17-dev; changes from
it are taken selectively and verified against 0.16.0.

MIT, see [LICENSE](LICENSE).
