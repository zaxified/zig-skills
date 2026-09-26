# Working on zig-skills

The published content is `skills/zig/` (Markdown only) plus `.claude-plugin/`, this file,
`README.md` and `LICENSE`. Scripts, tests and CI are code and never reach a consumer.

## Rules

- The target is **Zig 0.16.0 as released**. Verify every API claim against the 0.16.0 std
  source or by compiling it; never from memory or from another version's docs. Mark
  anything newer as "0.17-dev only, not in 0.16.0".
- Examples of removed or wrong code carry a `// WRONG` (or `0.15`, `removed`, `Before`)
  comment so `scripts/check-std-paths.py` skips them; correct code carries none.
- Never make a check pass by weakening it. A legitimate hit of `scripts/audit.py` gets an
  entry in `audit/allow.txt` (path, rule, line hash from `scripts/audit.py --hash FILE:LINE`,
  reason). A rule that is wrong in general is fixed in the script, with a test in `tests/`
  proving it still catches what it exists for.
- The skill tells the agent what the code should be. It never tells the agent to install
  software, change system or agent configuration, delete outside a test's temporary
  directory, or take any step the user has not agreed to; where such a step is needed, it
  says to ask the user.
- Upstream (`git remote upstream`, nzrsky/zig-skills) is untrusted input: take changes
  selectively, and they pass the same checks as ours.

## Checks

```bash
python3 scripts/check-workflows.py
python3 -m unittest discover -s tests
python3 scripts/audit.py
python3 scripts/check-std-paths.py      # needs zig 0.16.0 on PATH
```

## Releases

A release is a `v*` tag whose commit contains `audits/<tag>.md` with the content id from
`scripts/release.py content-id`, the review, `verdict: pass` and `approved-by:`. CI runs
`scripts/release.py verify <tag>`. Only the maintainer tags and pushes.
