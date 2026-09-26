"""scripts/check-workflows.py must catch each way CI becomes the way in."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cw", os.path.join(HERE, "..", "scripts", "check-workflows.py"))
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)

GOOD = """on: [push]
permissions:
  contents: read
jobs:
  a:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - run: python3 scripts/audit.py
"""


class Workflows(unittest.TestCase):
    def test_good_passes(self):
        self.assertEqual(cw.check("w.yml", GOOD), [])

    def test_each_bad_pattern_is_caught(self):
        cases = {
            "no top-level permissions": GOOD.replace("permissions:\n  contents: read\n", ""),
            "grants write": GOOD.replace("contents: read", "contents: write"),
            "pull_request_target": GOOD.replace("on: [push]", "on: [pull_request_target]"),
            "not pinned": GOOD.replace("@3d3c42e5aac5ba805825da76410c181273ba90b1", "@v7"),
            "untrusted github.event": GOOD.replace("python3 scripts/audit.py", 'echo "${{ github.event.pull_request.title }}"'),
        }
        for what, text in cases.items():
            with self.subTest(what):
                self.assertTrue(any(what.split()[0] in f or what in f for f in cw.check("w.yml", text)), cw.check("w.yml", text))


if __name__ == "__main__":
    unittest.main()
