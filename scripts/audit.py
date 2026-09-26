#!/usr/bin/env python3
"""Release safety gate for the zig skill.

A skill is not documentation a person reads; it is instructions an agent
carries out with the consumer's permissions. This gate refuses anything in
the published content that could turn against the consumer:

  files      the payload is plain Markdown only: no scripts, symlinks, binaries
  manifest   SKILL.md frontmatter and .claude-plugin/*.json use only keys that
             grant no execution (no hooks, allowed-tools, mcpServers, ...)
  unicode    no invisible or direction-changing characters (hidden text)
  markup     no HTML comments, raw HTML, images or reference-style links
             (places to hide text, or to leak data through a URL)
  url        every URL is on the domain allowlist and carries no query string
  command    no destructive or system-altering commands (rm -rf, curl | sh,
             force push, sudo, writes to dotfiles, ...)
  agent      no text addressed to the agent rather than about Zig
             ("ignore previous instructions", "do not tell the user", ...)
  secret     no credentials or private keys
  blob       no long encoded blobs
  advice     unsafe practices that need a stated reason where they appear

A legitimate hit (say, deleteTree on a test's tmpDir) is accepted only by an
entry in audit/allow.txt naming the file, the rule and a hash of the exact
line, with a reason. The exemption is visible in the diff and reviewed like
any other change; an entry that no longer matches anything is an error, so
exemptions cannot outlive the line they were written for.

Usage: scripts/audit.py [--root DIR] [--hash FILE:LINE]
Exit status 1 on any finding.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata

# What is published and therefore audited. Scripts, tests and CI are code and
# are reviewed as code; they never reach a consumer's agent.
PAYLOAD_DIR = "skills/zig"
AUDITED_EXTRA = ["README.md", "CLAUDE.md", "LICENSE", ".claude-plugin"]

MAX_FILE_BYTES = 256 * 1024

SKILL_KEYS = {"name", "description", "license", "compatibility", "metadata"}
PLUGIN_KEYS = {"name", "version", "description", "author", "homepage", "repository",
               "license", "keywords", "skills"}
MARKETPLACE_KEYS = {"$schema", "name", "owner", "metadata", "description", "version", "plugins"}
MARKETPLACE_PLUGIN_KEYS = {"name", "source", "description", "version", "author", "homepage",
                           "repository", "license", "keywords", "category", "tags", "strict", "skills"}

URL_DOMAINS = {
    "ziglang.org", "www.ziglang.org", "codeberg.org", "github.com", "raw.githubusercontent.com",
    "zig.guide", "zig.news", "en.wikipedia.org", "llvm.org", "www.rfc-editor.org",
    "datatracker.ietf.org", "man7.org", "pubs.opengroup.org", "semver.org", "spdx.org",
    "wtf-8.codeberg.page", "simonkagstrom.github.io", "json.org", "www.json.org",
    "unicode.org", "www.unicode.org", "kernel.org", "www.kernel.org", "sqlite.org",
    "www.sqlite.org", "cdn.jsdelivr.net", "docs.anthropic.com", "code.claude.com",
    "keepachangelog.com", "opensource.org", "lwn.net", "claude.ai", "www.swift.org",
}

# (rule, regex, message). Checked line by line over every audited file,
# prose and code blocks alike: an agent follows either.
COMMAND = [
    (r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)+", "recursive/forced rm"),
    (r"\brmdir\s+--ignore", "rmdir ignoring errors"),
    (r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|fi|k)?sh\b", "pipe download into a shell"),
    (r"\b(curl|wget)\b[^\n]*\s-[a-zA-Z]*[oO]\b", "download to a file"),
    (r"\bsudo\b", "sudo"),
    (r"\bsu\s+-", "su"),
    (r"\bgit\s+push\b", "git push"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s+\.|branch\s+-D|filter-branch|update-ref\s+-d)", "destructive git"),
    (r"--force\b|\s-f\s+origin\b", "force flag"),
    (r"--no-verify\b|--dangerously|skip-permissions|bypassPermissions", "bypass a safety check"),
    (r"\bchmod\s+(-R\s+)?[0-7]*7[0-7]{2}\b|\bchmod\s+[+ugoa]*s\b|\bchown\s+-R\b", "broad permission change"),
    (r"\b(dd\s+if=|mkfs\b|fdisk\b|parted\b|wipefs\b|shred\b|truncate\s+-s\s*0)", "disk / data destruction"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\b(kill|pkill|killall)\s+(-9\s+)?(-1\b|1\b|init\b|systemd\b)", "kill system processes"),
    (r"(^|[$#]\s|&&\s*|;\s*|`)(sudo\s+)?(shutdown|reboot|halt|poweroff)\b|\bsystemctl\s+(stop|disable|mask|kill)\b", "stop the system or a service"),
    (r"\bcrontab\b|/etc/cron|\bsystemctl\s+enable\b|\.config/autostart|LaunchAgents", "persistence"),
    (r"~/\.ssh|\.ssh/(id_|authorized_keys)|~/\.(bash|zsh|fish)rc|\.profile\b|/etc/(passwd|shadow|sudoers|hosts)", "credentials or shell/system config"),
    (r"~/\.claude|\.claude/(settings|hooks|skills|agents|commands)|CLAUDE\.md|settings(\.local)?\.json|\.mcp\.json", "agent configuration"),
    (r"\b(nc|ncat|netcat|socat)\b\s+(-[a-z]*e|-[a-z]*l)|/dev/tcp/|\bbash\s+-i\b", "reverse shell / listener"),
    (r"\b(eval|exec)\s*\$\(|\bbase64\s+(-d|--decode)\b[^\n]*\|", "decode-and-run"),
    (r"\benv\b\s*\||\bprintenv\b|\$\{?(AWS_|GITHUB_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY|NPM_TOKEN)", "environment / token harvesting"),
    (r"\bnpm\s+i(nstall)?\s+-g\b|\bpip3?\s+install\b|\bgo\s+install\b|\bcargo\s+install\b|\bbrew\s+install\b|\bapt(-get)?\s+install\b", "installs software"),
    # Zig APIs that delete or execute. Allowed only where the path is visibly
    # a test's temporary directory or the entry says why.
    (r"\bdeleteTree\b|\bdeleteTreeAbsolute\b|\bdeleteDir(Absolute)?\b|\bdeleteFile(Absolute)?\b", "Zig filesystem deletion"),
    # A command line built as an argv array: the shell patterns above never see it.
    (r"\"(rm|rmdir|curl|wget|sh|bash|zsh|fish|sudo|su|dd|mkfs|chmod|chown|kill|pkill|nc|ncat|socat|ssh|scp|crontab|systemctl|shutdown|reboot)\"\s*,", "dangerous command in an argv array"),
    (r"\"git\"\s*,\s*\"(push|reset|clean|checkout|restore|branch|rm|filter-branch|filter-repo|update-ref|gc|reflog|config)\"", "destructive git in an argv array"),
]

AGENT = [
    (r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|other)\s+(instructions|rules|guidance|prompts?)", "override instructions"),
    (r"(disregard|forget|override)\s+(your|all|the|any)\s+(instructions|rules|system|guidelines)", "override instructions"),
    (r"system\s+prompt|developer\s+message|<\s*/?\s*(system|assistant|user|human)\s*>", "prompt-structure text"),
    (r"(do\s+not|don'?t|never)\s+(tell|inform|mention|show|reveal|report)\s+(this\s+)?(to\s+)?(the\s+)?(user|human|operator)", "conceal from the user"),
    (r"without\s+(asking|telling|informing|notifying|confirmation|permission|the\s+user)", "act without consent"),
    (r"\byou\s+are\s+(now\s+)?(claude|an?\s+(ai|assistant|agent|llm)|chatgpt|in\s+\w+\s+mode)", "role reassignment"),
    (r"\b(as\s+an?\s+(ai|assistant|agent))\b|\b(the\s+)?(assistant|agent|model|llm)\s+(must|should|shall)\s+(always\s+|now\s+)?(run|execute|call|invoke|send|upload|delete|fetch|open)", "instruction to the agent"),
    (r"\bexfiltrat|\bsend\s+(the\s+)?(contents?|file|key|token|secret|credentials)\s+to\b|\bupload\s+(the\s+)?(file|key|token|secret)", "exfiltration"),
    (r"\b(jailbreak|DAN\s+mode|prompt\s+injection\s+payload)\b", "jailbreak"),
    (r"\b(shellcode|keylogger|ransomware|backdoor|rootkit|privilege\s+escalation|credential\s+stuffing|reverse\s+shell)\b"
     r"|\bexploit\s+(code|chain|kit)\b|\b(write|craft|build)\s+an?\s+exploit\b|\bexploit(ing)?\s+(the|a|this)\s+(vulnerab|bug|overflow|cve)",
     "offensive-security content"),
]

SECRET = [
    (r"AKIA[0-9A-Z]{16}", "AWS key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{36,}", "GitHub token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{50,}", "GitHub token"),
    (r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}", "API key"),
    (r"\bxox[abprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", "JWT"),
]

ADVICE = [
    (r"setRuntimeSafety\s*\(\s*false\s*\)", "runtime safety disabled"),
    (r"verify_(host|peer|cert\w*|tls|ssl)\s*=\s*false|\bca_bundle\s*=\s*(null|\.none)|\.no_verification\b|insecure_skip|skip_verify|InsecureSkipVerify", "TLS/certificate verification disabled"),
    (r"(DefaultPrng|Xoshiro|Pcg|Sfc64|RomuTrio|Isaac64)[^\n]*(key|token|secret|password|nonce|salt|iv)\b", "non-cryptographic RNG for secrets"),
    (r"(?i)\b(md5|sha1)\b[^\n]*\b(password|signature|sign|signing|auth|authentication|mac|hmac)\b"
     r"|(?i:\b(password|signature|signing|authentication|hmac)\b[^\n]*\b(md5|sha1)\b)", "broken hash for security use"),
]

BLOB = re.compile(r"[A-Za-z0-9+/=_-]{160,}")
URL = re.compile(r"\b(?:https?|ftp|file|data|javascript)://[^\s<>)\]`'\"]+|\b(?:data|javascript):[^\s)]+", re.I)
HTML_TAG = re.compile(r"<\s*/?\s*(script|iframe|img|a|div|span|details|summary|style|link|meta|object|embed|svg|form|input|base|br|p|table|pre|code)\b[^>]*>", re.I)
IMAGE = re.compile(r"!\[[^\]]*\]\(")
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S+")

# Characters that render as nothing or reorder text: the usual way to hide an
# instruction in plain sight. U+FE0F (emoji presentation) is allowed only
# right after a symbol, where it is what every editor inserts.
BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x200E, 0x200F, 0x061C}


def rel(root, p):
    return os.path.relpath(p, root).replace(os.sep, "/")


def line_hash(line):
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:16]


class Audit:
    def __init__(self, root):
        self.root = root
        self.findings = []  # (path, line, rule, msg, hash)
        self.allow = self.load_allow()
        self.used = set()

    def load_allow(self):
        allow = {}
        p = os.path.join(self.root, "audit", "allow.txt")
        if not os.path.exists(p):
            return allow
        with open(p, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        for n, raw in enumerate(lines, 1):
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split("\t")
            if len(parts) != 4 or len(parts[3].strip()) < 10:
                self.findings.append(("audit/allow.txt", n, "allow", "entry needs 4 tab-separated fields: path, rule, line hash, reason (>= 10 chars)", ""))
                continue
            allow[(parts[0], parts[1], parts[2])] = n
        return allow

    def hit(self, path, n, rule, msg, line=""):
        h = line_hash(line) if line else ""
        key = (path, rule, h)
        if h and key in self.allow:
            self.used.add(key)
            return
        self.findings.append((path, n, rule, msg, h))

    # ---- walkers ----

    def audited_files(self):
        out = []
        for base in [PAYLOAD_DIR] + AUDITED_EXTRA:
            p = os.path.join(self.root, base)
            if os.path.islink(p):
                out.append(p)
            elif os.path.isdir(p):
                for d, dirs, files in os.walk(p, followlinks=False):
                    dirs.sort()
                    for f in sorted(files + [x for x in dirs if os.path.islink(os.path.join(d, x))]):
                        out.append(os.path.join(d, f))
            elif os.path.exists(p):
                out.append(p)
        return out

    def run(self):
        for p in self.audited_files():
            r = rel(self.root, p)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                self.hit(r, 0, "files", "symlink in published content")
                continue
            if not stat.S_ISREG(st.st_mode):
                self.hit(r, 0, "files", "not a regular file")
                continue
            if st.st_mode & 0o111:
                self.hit(r, 0, "files", "executable bit set")
            if st.st_size > MAX_FILE_BYTES:
                self.hit(r, 0, "files", f"larger than {MAX_FILE_BYTES} bytes")
            in_payload = r.startswith(PAYLOAD_DIR + "/")
            if in_payload and not r.endswith(".md"):
                self.hit(r, 0, "files", "payload may contain only .md files")
                continue
            with open(p, "rb") as fh:
                raw = fh.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                self.hit(r, 0, "files", f"not UTF-8: {e}")
                continue
            if r.endswith(".json"):
                self.check_json(r, text)
            if r == PAYLOAD_DIR + "/SKILL.md":
                self.check_frontmatter(r, text)
            self.check_text(r, text, markdown=r.endswith(".md"))
        for key, n in self.allow.items():
            if key not in self.used:
                self.findings.append(("audit/allow.txt", n, "allow", f"stale entry, matches nothing: {key[0]} {key[1]} {key[2]}", ""))
        return self.findings

    # ---- checks ----

    def check_frontmatter(self, r, text):
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not m:
            self.hit(r, 1, "manifest", "SKILL.md has no frontmatter")
            return
        keys = re.findall(r"^([A-Za-z_-][\w-]*)\s*:", m.group(1), re.M)
        for k in keys:
            if k not in SKILL_KEYS:
                self.hit(r, 1, "manifest", f"frontmatter key '{k}' not allowed (only {sorted(SKILL_KEYS)})")
        top = re.search(r"^name:\s*(\S+)", m.group(1), re.M)
        if not top or top.group(1) != "zig":
            self.hit(r, 1, "manifest", "frontmatter name must be 'zig'")

    def check_json(self, r, text):
        try:
            data = json.loads(text)
        except ValueError as e:
            self.hit(r, 0, "manifest", f"invalid JSON: {e}")
            return
        if not isinstance(data, dict):
            self.hit(r, 0, "manifest", "top level must be an object")
            return
        name = os.path.basename(r)
        if name == "plugin.json":
            allowed = PLUGIN_KEYS
        elif name == "marketplace.json":
            allowed = MARKETPLACE_KEYS
        else:
            self.hit(r, 0, "manifest", "unexpected JSON file in published content")
            return
        for k in data:
            if k not in allowed:
                self.hit(r, 0, "manifest", f"key '{k}' not allowed (grants execution or is unknown)")
        if name == "marketplace.json":
            for i, pl in enumerate(data.get("plugins", [])):
                for k in pl:
                    if k not in MARKETPLACE_PLUGIN_KEYS:
                        self.hit(r, 0, "manifest", f"plugins[{i}].{k} not allowed")
                src = pl.get("source")
                if not (isinstance(src, str) and src.startswith("./")):
                    self.hit(r, 0, "manifest", f"plugins[{i}].source must be a path inside this repo")
        for s in [v for v in _strings(data)]:
            if isinstance(s, str) and re.search(r"\.\.|^/|\$\{", s) and not re.match(r"https?://", s):
                self.hit(r, 0, "manifest", f"path escapes the plugin or expands variables: {s!r}")

    def check_text(self, r, text, markdown):
        in_code = False
        for n, line in enumerate(text.split("\n"), 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
            self.check_unicode(r, n, line)
            if markdown and not in_code:
                if "<!--" in line or "-->" in line:
                    self.hit(r, n, "markup", "HTML comment (hidden text)", line)
                if HTML_TAG.search(line):
                    self.hit(r, n, "markup", "raw HTML", line)
                if IMAGE.search(line):
                    self.hit(r, n, "markup", "image (renders remote content, can leak through its URL)", line)
                if REF_DEF.match(line):
                    self.hit(r, n, "markup", "reference-style link definition (invisible when rendered)", line)
            for u in URL.finditer(line):
                inline = line[: u.start()].count("`") % 2 == 1
                self.check_url(r, n, u.group(0), line, in_code or inline)
            for rules, rule in ((COMMAND, "command"), (AGENT, "agent"), (SECRET, "secret"), (ADVICE, "advice")):
                for pat, msg in rules:
                    if re.search(pat, line, re.I if rule == "agent" else 0):
                        self.hit(r, n, rule, msg, line)
            if BLOB.search(line) and not URL.search(line):
                self.hit(r, n, "blob", "long encoded run", line)

    def check_unicode(self, r, n, line):
        prev = ""
        for ch in line:
            cp = ord(ch)
            cat = unicodedata.category(ch)
            bad = None
            if cp in BIDI:
                bad = "bidirectional control"
            elif 0xE0000 <= cp <= 0xE007F:
                bad = "tag character"
            elif 0xE0100 <= cp <= 0xE01EF or (0xFE00 <= cp <= 0xFE0E):
                bad = "variation selector"
            elif cp == 0xFE0F and not (prev and unicodedata.category(prev) in ("So", "Sm", "Po")):
                bad = "variation selector"
            elif cat == "Cf":
                bad = "invisible format character"
            elif cat in ("Co", "Cs", "Cn"):
                bad = "private-use / unassigned code point"
            elif cat == "Cc" and ch not in "\t\r":
                bad = "control character"
            elif cat == "Zs" and ch != " ":
                bad = "non-ASCII space"
            if bad:
                self.hit(r, n, "unicode", f"{bad} U+{cp:04X}", line)
            prev = ch

    def check_url(self, r, n, url, line, in_code=False):
        m = re.match(r"(?i)(https?)://(?:[^/@?#]*@)?([^/:?#]+)", url)
        if not m:
            self.hit(r, n, "url", f"scheme not allowed: {url[:60]}", line)
            return
        host = m.group(2).lower()
        if in_code and _example_host(host):
            # Test data in an example (URI parsing, a request builder): not a
            # link anyone follows, and reserved names resolve nowhere.
            return
        if m.group(1).lower() != "https":
            self.hit(r, n, "url", f"plain http: {url[:80]}", line)
        if host not in URL_DOMAINS:
            self.hit(r, n, "url", f"domain not on allowlist: {host}", line)
        if "?" in url:
            self.hit(r, n, "url", f"query string in URL: {url[:80]}", line)


def _example_host(host):
    """RFC 2606 / 6761 reserved names and RFC 3986's one-letter examples."""
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "...") or re.fullmatch(r"[a-z]", host):
        return True
    return bool(re.search(r"(^|\.)(example\.(com|org|net)|example|test|invalid|localhost)$", host))


def _strings(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    else:
        yield x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--hash", metavar="FILE:LINE", help="print the allow.txt hash of one line and exit")
    args = ap.parse_args()
    if args.hash:
        f, ln = args.hash.rsplit(":", 1)
        print(line_hash(open(os.path.join(args.root, f), encoding="utf-8").read().split("\n")[int(ln) - 1]))
        return 0
    findings = Audit(args.root).run()
    for path, n, rule, msg, h in findings:
        print(f"{path}:{n}: [{rule}] {msg}" + (f"  (hash {h})" if h else ""))
    by = {}
    for f in findings:
        by[f[2]] = by.get(f[2], 0) + 1
    print(f"{len(findings)} finding(s)" + (": " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())) if by else ""), file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
