"""The markers that switch checking off must not switch it off by accident.

A prose comment containing "before" once disabled path checking for the rest
of its block, and a heading such as "Build System (0.15.x)" (meaning
"introduced in 0.15") would have excluded current code.
"""
import importlib.util
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("paths", os.path.join(HERE, "..", "scripts", "check-std-paths.py"))
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)


class Markers(unittest.TestCase):
    def test_wrong_markers_only_at_comment_start(self):
        for line in ("// WRONG (0.15)", "// Before:", "    // 0.15.x API", "// OLD", "// ❌ compile error"):
            self.assertTrue(paths.WRONG_LINE.search(line), line)
        for line in ("// Check before expensive operation", "x(); // removed the old one", "// the transition before t"):
            self.assertFalse(paths.WRONG_LINE.search(line), line)

    def test_old_heading_needs_an_explicit_word(self):
        old = ["## TCP Server (0.15.x, removed in 0.16)", "### Old API (DEPRECATED)"]
        current = ["## Critical: Build System (0.15.x)", "# std.http Reference (0.16.0)",
                   "### Monotonic timing (`std.time.Timer` removed)", "## Migration from 0.15"]
        for h in old:
            self.assertTrue(paths.OLD_HEADING.match(h), h)
        for h in current:
            self.assertFalse(paths.OLD_HEADING.match(h), h)

    def test_subsection_inherits_old_section(self):
        text = "## TCP Server (0.15.x, removed in 0.16)\n\n### Basic Server\n\n```zig\nx\n```\n## Next (0.16)\n### Sub\n```zig\ny\n```\n"
        blocks = list(paths.BLOCK.finditer(text))
        self.assertTrue(paths.in_old_section(text, blocks[0].start()))
        self.assertFalse(paths.in_old_section(text, blocks[1].start()))

    def test_aliases_are_resolved_and_shadowed(self):
        text = ("```zig\nconst ascii = std.ascii;\n```\n"
                "```zig\nconst x = ascii.findIgnoreCase(a, b);\n```\n"
                "```zig\nvar ascii = Local.init();\nascii.update(a);\n```\n"
                "```zig\n// WRONG\nconst rnd = std.crypto.random;\n```\n")
        table = paths.aliases(text)
        self.assertEqual(table, {"ascii": ".ascii"})  # the WRONG block's alias does not count
        self.assertEqual(paths.expand("ascii.findIgnoreCase(a)", table), "std.ascii.findIgnoreCase(a)")
        self.assertEqual(paths.expand("my_ascii.x + .ascii.y", table), "my_ascii.x + .ascii.y")
        shadowing = "var ascii = Local.init();\nascii.update(a);\n"
        self.assertEqual(paths.block_table(shadowing, table), {})

    def test_io_arity(self):
        self.assertTrue(paths.IO_ARITY.search("file.close();"))
        self.assertTrue(paths.IO_ARITY.search("try std.Io.Dir.cwd().openFile(path, .{})"))
        self.assertFalse(paths.IO_ARITY.search("try std.Io.Dir.cwd().openFile(io, path, .{})"))
        self.assertTrue(paths.FILE_GONE.search("try file.writeAll(x);"))
        self.assertFalse(paths.FILE_GONE.search("try writer.writeAll(x);"))


dspec = importlib.util.spec_from_file_location("deprecated", os.path.join(HERE, "..", "scripts", "check-deprecated.py"))
deprecated = importlib.util.module_from_spec(dspec)
dspec.loader.exec_module(deprecated)

FAKE_STD = {
    "std.zig": '/// Deprecated; use `lang`.\npub const builtin = lang;\npub const lang = @import("lang.zig");\n',
    "fmt.zig": ('/// Deprecated in favor of `Allocator.print`.\npub fn allocPrint() void {}\n'
                'pub fn bufPrint() void {}\n'),
    "heap.zig": ('/// The minimum page size.\npub const page_size_min: usize = x orelse @compileError("no");\n'
                 '/// Default initialization of this struct is deprecated; use `.empty` instead.\npub const Arena = struct {};\n'),
    "testing.zig": 'pub const allocator = if (is_test) a else @compileError("not testing");\n',
    "Uri.zig": 'pub const getHost = @compileError("moved to HostName.fromUri");\n',
    "array_list.zig": ('pub fn Aligned() type { return struct {\n'
                       '    /// Deprecated in favor of `last`\n    pub const getLastOrNull = last;\n'
                       '    /// Deprecated in favor of `popLast`\n    pub fn pop() void {}\n'
                       '    pub fn last() void {}\n}; }\n'),
    "deque.zig": 'pub fn D() type { return struct {\n    pub fn pop() void {}\n}; }\n',
    "fs/path.zig": '/// Deprecated in favor of `relativeAlloc`.\npub fn relative() void {}\n',
}


class Deprecated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        for rel, body in FAKE_STD.items():
            path = os.path.join(cls.tmp.name, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
        cls.q, cls.m = deprecated.scan_std(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def hit(self, code):
        return deprecated.line_hit(code, self.q, self.m)

    def test_qualified_deprecated_and_removed(self):
        self.assertEqual(self.hit("const s = try std.fmt.allocPrint(a, x, .{});")[0], "std.fmt.allocPrint")
        self.assertEqual(self.hit("const B = std.builtin.Type;")[0], "std.builtin")
        self.assertEqual(self.hit("_ = std.Uri.getHost;")[0], "std.Uri.getHost")
        self.assertEqual(self.hit("std.fs.path.relative(a, b)")[0], "std.fs.path.relative")

    def test_alive_and_lookalikes_pass(self):
        for code in ("_ = try std.fmt.bufPrint(&b, x, .{});",
                     "const p = std.heap.page_size_min;",           # @compileError inside an expression
                     "var a: std.heap.Arena = .{};",                 # field-default deprecation, not the decl
                     "const gpa = std.testing.allocator;",           # "not testing" guard
                     "@memcpy(buf[0..relative.len], relative);",     # range end, namespace-only name
                     "const x = q.pop();"):                          # pop is alive elsewhere
            self.assertIsNone(self.hit(code), code)

    def test_member_only_when_unique(self):
        self.assertEqual(self.hit("if (list.getLastOrNull()) |x| {}")[0], ".getLastOrNull")

    def test_language_rules_follow_the_zig_version(self):
        # 0.17 removals are not findings on 0.16; @Type was removed in 0.16.
        self.assertIsNone(deprecated.line_hit("const n = @intFromEnum(e);", self.q, self.m, (0, 16)))
        self.assertIsNotNone(deprecated.line_hit("const n = @intFromEnum(e);", self.q, self.m, (0, 17)))
        self.assertIsNotNone(deprecated.line_hit("const T = @Type(.{ .int = x });", self.q, self.m, (0, 16)))

    def test_language_rules(self):
        bad = ["const z = [_]u8{0} ** 16;", 'const s = "ab" ** 3;', "errdefer |err| log(err);",
               "const v = void{};", "const x: i0 = 0;", "const c = @cImport(@cInclude(\"a.h\"));",
               "const n = @intFromEnum(e);", 'inline for (@typeInfo(T).@"struct".fields) |f| {}',
               ".linkage = .internal,", "if (b.args) |args| run.addArgs(args);",
               'for (@typeInfo(E).@"enum".fields) |f| {}', 'inline for (@typeInfo(T).@"struct".decls) |d| {}',
               "if (info.is_exhaustive) {}", 'const ps = @typeInfo(F).@"fn".params;',
               "if (@typeInfo(P).pointer.is_const) {}",
               "const T = @Type(.{ .int = .{ .signedness = .unsigned, .bits = 3 } });",
               "if (builtin.os.tag == .windows) {}", "const a = builtin.cpu.arch;"]
        for code in bad:
            self.assertIsNotNone(self.hit(code), code)
        good = ["const z: [16]u8 = @splat(0);", "const p = a ** b;", "errdefer gpa.free(x);",
                "const n = @backingInt(e);", 'inline for (info.field_names) |n| {}', "const u: u0 = 0;",
                "run.addPassthruArgs();", ".linkage = .strong,",
                'for (@typeInfo(E).@"enum".field_names) |n| {}', "if (info.mode == .exhaustive) {}",
                'const c = @typeInfo(P).pointer.attrs.@"const";', "const a = std.mem.Alignment.of(T);",
                "if (builtin.target.os.tag == .windows) {}", "const m = builtin.mode;"]
        for code in good:
            self.assertIsNone(self.hit(code), code)


if __name__ == "__main__":
    unittest.main()
