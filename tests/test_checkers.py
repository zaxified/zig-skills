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

    def test_io_arity(self):
        self.assertTrue(paths.IO_ARITY.search("file.close();"))
        self.assertTrue(paths.IO_ARITY.search("try std.Io.Dir.cwd().openFile(path, .{})"))
        self.assertFalse(paths.IO_ARITY.search("try std.Io.Dir.cwd().openFile(io, path, .{})"))
        self.assertTrue(paths.FILE_GONE.search("try file.writeAll(x);"))
        self.assertFalse(paths.FILE_GONE.search("try writer.writeAll(x);"))


if __name__ == "__main__":
    unittest.main()
