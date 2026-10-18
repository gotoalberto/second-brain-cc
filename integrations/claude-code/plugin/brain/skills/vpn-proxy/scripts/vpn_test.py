#!/usr/bin/env python3
"""Tests for vpn.py with a fake kp.py and a fake wireproxy (no network, no real keys).

Run: python3 vpn_test.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "vpn.py")
sys.path.insert(0, HERE)
import vpn as V  # noqa: E402

KEY = "test-private-key-1a2b3c4d="
NOTES = """[Interface]
# Key for a test exit
PrivateKey = {{PRIVATE_KEY}}
Address = 10.2.0.2/32, fd00:0f0f::2/128
DNS = 10.2.0.1, fd00:0f0f::1

[Peer]
PublicKey = test-public-key-0f0f0f0f=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 192.0.2.10:51820
"""

FAKE_KP = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_KP_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
entries = json.load(open(os.environ["FAKE_KP_ENTRIES"]))
entry = args[1]
if entry not in entries:
    sys.stderr.write("entry not found\n"); sys.exit(4)
attr = args[args.index("-a") + 1] if "-a" in args else "Password"
value = entries[entry]["notes" if attr.lower() == "notes" else "password"]
assert "--pipe" in args and args[args.index("--pipe") + 1] == "cat", args
sys.stdout.write(value)
"""

# Listens on the BindAddress of its config and copies the config it was given, so the test can
# check what wireproxy would have read after vpn.py deleted the file.
FAKE_WIREPROXY = r"""#!/usr/bin/env python3
import os, re, socket, sys, time
conf = sys.argv[sys.argv.index("-c") + 1]
body = open(conf).read()
open(os.environ["FAKE_WP_COPY"], "w").write(body)
port = int(re.search(r"BindAddress = 127\.0\.0\.1:(\d+)", body).group(1))
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port)); s.listen(5)
time.sleep(60)
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class VpnLogicTest(unittest.TestCase):
    def test_parse_exits_assigns_ports_in_order(self):
        self.assertEqual(V.parse_exits("aa, bb=1090 ,cc"),
                         [("aa", 1080), ("bb", 1090), ("cc", 1082)])

    def test_parse_exits_rejects_bad_names_and_duplicates(self):
        for spec in ("aa,aa", "a b", "aa=notaport", "aa=70000", "../x"):
            with self.assertRaises(ValueError, msg=spec):
                V.parse_exits(spec)

    def test_parse_exits_empty(self):
        self.assertEqual(V.parse_exits(""), [])
        self.assertEqual(V.parse_exits(None), [])

    def test_render_config_fills_key_drops_comments_and_ipv6(self):
        body = V.render_config(NOTES, KEY, 1080)
        self.assertIn("PrivateKey = " + KEY, body)
        self.assertNotIn("{{PRIVATE_KEY}}", body)
        self.assertNotIn("# Key", body)
        self.assertIn("Address = 10.2.0.2/32\n", body)
        self.assertIn("DNS = 10.2.0.1\n", body)
        self.assertNotIn("fd00", body)
        self.assertTrue(body.rstrip().endswith("[Socks5]\nBindAddress = 127.0.0.1:1080"))

    def test_render_config_refuses_notes_without_interface_or_placeholder(self):
        with self.assertRaises(ValueError):
            V.render_config("just some text", KEY, 1080)
        with self.assertRaises(ValueError):
            V.render_config("[Interface]\nPrivateKey = inline-key\n", KEY, 1080)

    def test_kp_entry_uses_prefix(self):
        self.assertEqual(V.kp_entry("aa", "infra/vpn-wg-"), "infra/vpn-wg-aa")

    def test_asset_name(self):
        self.assertEqual(V.asset_name("Linux", "x86_64"), "wireproxy_linux_amd64.tar.gz")
        self.assertEqual(V.asset_name("Darwin", "arm64"), "wireproxy_darwin_arm64.tar.gz")
        self.assertIsNone(V.asset_name("Windows", "AMD64"))


class VpnProcessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.port = free_port()
        self.kp = self.write("kp.py", FAKE_KP)
        self.wp = self.write("wireproxy", FAKE_WIREPROXY)
        self.entries = os.path.join(self.tmp, "entries.json")
        with open(self.entries, "w") as fh:
            json.dump({"infra/vpn-wg-aa": {"password": KEY, "notes": NOTES}}, fh)
        self.env = dict(os.environ, BRAIN_KP_SCRIPT=self.kp, VPN_PROXY_WIREPROXY=self.wp,
                        VPN_PROXY_STATE=os.path.join(self.tmp, "state"),
                        VPN_PROXY_EXITS="aa=%d,bb" % self.port, FAKE_KP_ENTRIES=self.entries,
                        FAKE_KP_LOG=os.path.join(self.tmp, "kp.log"),
                        FAKE_WP_COPY=os.path.join(self.tmp, "conf-copy"))
        self.env.pop("VPN_PROXY_KP_PREFIX", None)

    def tearDown(self):
        self.run_it("down", "all")

    def write(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        return path

    def run_it(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env=self.env, timeout=60, stdin=subprocess.DEVNULL)

    def test_list_shows_exits_and_refs(self):
        r = self.run_it("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("aa", r.stdout)
        self.assertIn("socks5://127.0.0.1:%d" % self.port, r.stdout)
        self.assertIn("kp://infra/vpn-wg-bb", r.stdout)

    def test_no_exits_configured(self):
        self.env["VPN_PROXY_EXITS"] = ""
        r = self.run_it("up", "aa", "--no-ip")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("VPN_PROXY_EXITS", r.stderr)

    def test_up_unknown_exit(self):
        r = self.run_it("up", "zz", "--no-ip")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown exit", r.stderr)

    def test_up_then_down(self):
        r = self.run_it("up", "aa", "--no-ip")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("socks5://127.0.0.1:%d" % self.port, r.stdout)
        self.assertNotIn(KEY, r.stdout + r.stderr)
        with open(self.env["FAKE_WP_COPY"]) as fh:
            self.assertIn("PrivateKey = " + KEY, fh.read())
        state = self.env["VPN_PROXY_STATE"]
        self.assertEqual([f for f in os.listdir(state) if f.endswith((".conf", ".key"))], [])
        with open(self.env["FAKE_KP_LOG"]) as fh:
            calls = [json.loads(l) for l in fh]
        self.assertTrue(all("--show" not in c for c in calls))
        self.assertTrue(all("--pipe" in c for c in calls))
        r = self.run_it("status", "--no-ip")
        self.assertIn("aa up", r.stdout)
        r = self.run_it("down", "aa")
        self.assertIn("aa down", r.stdout)
        for _ in range(20):
            if not V.port_open(self.port):
                break
            time.sleep(0.1)
        self.assertFalse(V.port_open(self.port))

    def test_up_missing_entry_fails_cleanly(self):
        r = self.run_it("up", "bb", "--no-ip")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("kp://infra/vpn-wg-bb", r.stderr)
        self.assertNotIn(KEY, r.stdout + r.stderr)


def main():
    """unittest, plus the `RESULT: N passed, M failed` line _bin/run_all_tests.py adds up."""
    suite = unittest.TestSuite()
    for case in (VpnLogicTest, VpnProcessTest):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    failed = len(result.failures) + len(result.errors)
    print("\nRESULT: %d passed, %d failed" % (result.testsRun - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
