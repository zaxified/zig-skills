"""scripts/release.py: the CI verdict that gates `tag` and the installer."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rel", os.path.join(HERE, "..", "scripts", "release.py"))
rel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rel)


def run(branch, status="completed", conclusion="success", rid=1):
    return {"id": rid, "name": "gate", "head_branch": branch, "status": status, "conclusion": conclusion}


class CiVerdict(unittest.TestCase):
    def test_no_runs_refused(self):
        self.assertFalse(rel.ci_verdict([])[0])

    def test_all_success_passes(self):
        self.assertTrue(rel.ci_verdict([run("main"), run("v0.17.0-r3", rid=2)])[0])

    def test_red_tag_run_condemns_a_green_main_run(self):
        # the r2/r4 shape: main green earlier, the scanner on the tag push red
        ok, why = rel.ci_verdict([run("main"), run("v0.17.0-r4", conclusion="failure", rid=2)])
        self.assertFalse(ok)
        self.assertIn("v0.17.0-r4", why)

    def test_running_is_not_yet_a_pass(self):
        self.assertFalse(rel.ci_verdict([run("main"), run("v1", status="in_progress", conclusion=None, rid=2)])[0])

    def test_cancelled_or_skipped_is_not_success(self):
        for c in ("cancelled", "skipped", "timed_out", None):
            with self.subTest(c=c):
                self.assertFalse(rel.ci_verdict([run("main", conclusion=c)])[0])


class TagName(unittest.TestCase):
    def test_malformed_names_refused_before_any_git_call(self):
        for bad in ("v0.17.0", "0.17.0-r5", "v0.17.0-r5;rm", "v0.17.0-r", ""):
            with self.subTest(bad=bad):
                self.assertEqual(rel.tag(bad), 1)


if __name__ == "__main__":
    unittest.main()
