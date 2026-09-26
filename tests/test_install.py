"""scripts/install.py must never touch anything outside its destination."""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("inst", os.path.join(HERE, "..", "scripts", "install.py"))
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class RemovePrevious(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.dest = os.path.join(self.root, "proj", ".claude", "skills", "zig")
        self.victim = os.path.join(self.root, "victim.txt")
        write(self.victim, "keep me")
        write(os.path.join(self.dest, "SKILL.md"), "x")

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, paths):
        write(os.path.join(self.dest, inst.MANIFEST), json.dumps({"files": [{"path": p, "sha256": "0"} for p in paths]}))

    def test_traversal_and_absolute_paths_refused(self):
        for bad in ("../../../../victim.txt", self.victim, "a/../../x", "./SKILL.md", "", "a\\\\b"):
            with self.subTest(bad=bad):
                self.manifest(["SKILL.md", bad])
                with self.assertRaises(SystemExit):
                    inst.remove_previous(self.dest)
                self.assertTrue(os.path.exists(self.victim))
                self.assertTrue(os.path.exists(os.path.join(self.dest, "SKILL.md")), "nothing removed on refusal")

    def test_symlinked_directory_refused(self):
        outside = os.path.join(self.root, "outside")
        write(os.path.join(outside, "f.md"), "keep")
        os.symlink(outside, os.path.join(self.dest, "references"))
        self.manifest(["SKILL.md", "references/f.md"])
        with self.assertRaises(SystemExit):
            inst.remove_previous(self.dest)
        self.assertTrue(os.path.exists(os.path.join(outside, "f.md")))

    def test_foreign_file_stops_before_any_removal(self):
        write(os.path.join(self.dest, "mine.md"), "user file")
        self.manifest(["SKILL.md"])
        with self.assertRaises(SystemExit):
            inst.remove_previous(self.dest)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "SKILL.md")))
        self.assertTrue(os.path.exists(os.path.join(self.dest, "mine.md")))

    def test_clean_previous_install_is_removed(self):
        write(os.path.join(self.dest, "references", "a.md"), "x")
        self.manifest(["SKILL.md", "references/a.md"])
        inst.remove_previous(self.dest)
        self.assertFalse(os.path.exists(self.dest))
        self.assertTrue(os.path.exists(self.victim))


if __name__ == "__main__":
    unittest.main()
