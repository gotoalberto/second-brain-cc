#!/usr/bin/env python3
"""Tests for agy_run.py with a fake agy binary. Run: python3 agy_run_test.py"""
import json, os, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "agy_run.py")

FAKE = r"""#!/usr/bin/env python3
import json, os, sys
open(os.environ["FAKE_ARGS"], "w").write(json.dumps(sys.argv[1:]))
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "ok":
    if "--dangerously-skip-permissions" in sys.argv:
        open("made_by_agy.txt", "w").write("hi")
    print(json.dumps({"conversation_id": "c1", "status": "SUCCESS", "response": "pong", "num_turns": 1,
                      "duration_seconds": 1.0, "usage": {"total_tokens": 10}}))
elif mode == "noise":
    print("some log line")
    print(json.dumps({"status": "SUCCESS", "response": "pong"}))
elif mode == "empty":
    sys.stderr.write("boom\n")
    sys.exit(2)
elif mode == "denied":
    print(json.dumps({"status": "SUCCESS", "response": "", "denied_actions": [{"action": "command"}]}))
"""


class AgyRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = os.path.join(self.tmp, "agy")
        with open(self.fake, "w") as f:
            f.write(FAKE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)
        self.argsfile = os.path.join(self.tmp, "args.json")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        g = lambda *a, cwd=self.repo: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
        g("init", "-q")
        g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        self.wt = os.path.join(self.tmp, "wt")
        g("worktree", "add", "-q", "-b", "wt", self.wt)

    def run_it(self, *args, mode="ok"):
        env = dict(os.environ, AGY_BIN=self.fake, FAKE_ARGS=self.argsfile, FAKE_MODE=mode)
        r = subprocess.run([sys.executable, RUN, *args], capture_output=True, text=True, env=env)
        return r.returncode, json.loads(r.stdout)

    def sent_args(self):
        return json.load(open(self.argsfile))

    def test_read_mode_is_sandboxed_without_skip(self):
        code, res = self.run_it("run", "--dir", self.repo, "--prompt", "hi")
        self.assertEqual(code, 0)
        self.assertEqual(res["response"], "pong")
        args = self.sent_args()
        self.assertIn("--sandbox", args)
        self.assertIn("--add-dir", args)
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertEqual(args[args.index("--output-format") + 1], "json")

    def test_write_refused_in_main_checkout(self):
        code, res = self.run_it("run", "--dir", self.repo, "--prompt", "hi", "--write")
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "INVALID")
        self.assertFalse(os.path.exists(self.argsfile))

    def test_write_in_worktree_reports_changes(self):
        code, res = self.run_it("run", "--dir", self.wt, "--prompt", "hi", "--write")
        self.assertEqual(code, 0)
        self.assertIn("--dangerously-skip-permissions", self.sent_args())
        self.assertIn("made_by_agy.txt", res["changed_files"])

    def test_write_allowed_in_scratch_dir_outside_repos(self):
        scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(scratch)
        code, res = self.run_it("run", "--dir", scratch, "--prompt", "hi", "--write")
        self.assertEqual(code, 0)
        self.assertIn("--dangerously-skip-permissions", self.sent_args())
        self.assertNotIn("changed_files", res)

    def test_noise_before_envelope(self):
        code, res = self.run_it("run", "--dir", self.repo, "--prompt", "hi", mode="noise")
        self.assertEqual((code, res["status"]), (0, "SUCCESS"))

    def test_no_envelope_is_error(self):
        code, res = self.run_it("run", "--dir", self.repo, "--prompt", "hi", mode="empty")
        self.assertEqual(code, 1)
        self.assertIn("no JSON envelope", res["error"])
        self.assertIn("boom", res["stderr_tail"])

    def test_denied_actions_surface(self):
        _, res = self.run_it("run", "--dir", self.repo, "--prompt", "hi", mode="denied")
        self.assertEqual(res["denied_actions"][0]["action"], "command")

    def test_bad_timeout(self):
        code, res = self.run_it("run", "--dir", self.repo, "--prompt", "hi", "--timeout", "soon")
        self.assertEqual((code, res["status"]), (1, "INVALID"))

    def test_options_forwarded(self):
        self.run_it("run", "--dir", self.repo, "--prompt", "hi", "--model", "example-model-high",
                    "--effort", "high", "--timeout", "20m")
        args = self.sent_args()
        self.assertEqual(args[args.index("--model") + 1], "example-model-high")
        self.assertEqual(args[args.index("--print-timeout") + 1], "20m")


def main():
    """unittest, plus the `RESULT: N passed, M failed` line _bin/run_all_tests.py adds up."""
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(AgyRunTest))
    failed = len(result.failures) + len(result.errors)
    print("\nRESULT: %d passed, %d failed" % (result.testsRun - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
