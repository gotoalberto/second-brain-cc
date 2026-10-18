#!/usr/bin/env python3
"""Tests for av.sh, the runtime wrapper of the animated-video skill, with a fake node and runtime.

Nothing is installed: the runtime is a temp directory marked ready and `node` is a script that
records how it was called.

Run: python3 av_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "av.sh")
SKILL = os.path.dirname(HERE)

FAKE_NODE = r"""#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_NODE_LOG"], "w") as fh:
    json.dump({"argv": sys.argv[1:], "node_path": os.environ.get("NODE_PATH", "")}, fh)
"""


class AvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rt = os.path.join(self.tmp, "runtime")
        os.makedirs(self.rt)
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        node = os.path.join(bindir, "node")
        with open(node, "w") as fh:
            fh.write(FAKE_NODE)
        os.chmod(node, 0o755)
        self.log = os.path.join(self.tmp, "node.json")
        self.env = dict(os.environ, ANIMATED_VIDEO_RUNTIME=self.rt, FAKE_NODE_LOG=self.log,
                        PATH=bindir + os.pathsep + os.environ.get("PATH", ""))
        self.env.pop("NODE_PATH", None)

    def mark_ready(self):
        version = subprocess.run(["bash", SCRIPT, "--pinned-version"], capture_output=True, text=True,
                                 env=self.env).stdout.strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        with open(os.path.join(self.rt, ".ready"), "w") as fh:
            fh.write("ok %s\n" % version)

    def run_it(self, *args):
        return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=self.env,
                              timeout=60, stdin=subprocess.DEVNULL)

    def test_no_arguments_prints_usage(self):
        r = self.run_it()
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stdout)

    def test_unknown_tool(self):
        self.mark_ready()
        r = self.run_it("no-such-tool")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no tool no-such-tool", r.stdout)

    def test_runs_the_tool_with_the_runtime_on_node_path(self):
        self.mark_ready()
        r = self.run_it("build", "pieces/bakery-short", "--fast")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.log) as fh:
            seen = json.load(fh)
        self.assertEqual(seen["argv"], [os.path.join(SKILL, "tools", "build.mjs"), "pieces/bakery-short", "--fast"])
        self.assertEqual(seen["node_path"].split(os.pathsep)[0], os.path.join(self.rt, "node_modules"))

    def test_rejects_a_tool_name_that_walks_out_of_tools(self):
        self.mark_ready()
        r = self.run_it("../tools/build")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(self.log))


def main():
    """unittest, plus the `RESULT: N passed, M failed` line _bin/run_all_tests.py adds up."""
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(AvTest))
    failed = len(result.failures) + len(result.errors)
    print("\nRESULT: %d passed, %d failed" % (result.testsRun - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
