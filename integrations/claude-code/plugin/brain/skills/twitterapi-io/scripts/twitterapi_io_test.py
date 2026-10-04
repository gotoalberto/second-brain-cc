#!/usr/bin/env python3
"""Tests for twitterapi_io.py against a local HTTP server and a fake kp.py.

Run: python3 twitterapi_io_test.py
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "twitterapi_io.py")
KEY = "test-key-1a2b3c4d"

FAKE_KP = r"""#!/usr/bin/env python3
import json, os, sys
open(os.environ["FAKE_KP_ARGS"], "w").write(json.dumps(sys.argv[1:]))
mode = os.environ.get("FAKE_KP_MODE", "ok")
if mode == "fail":
    sys.stderr.write("entry not found\n")
    sys.exit(4)
if mode == "empty":
    sys.exit(0)
print(os.environ["FAKE_KP_KEY"])
"""


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []
    status = 200

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        Handler.seen.append({"path": parsed.path,
                             "query": dict(urllib.parse.parse_qsl(parsed.query)),
                             "key": self.headers.get("x-api-key")})
        body = json.dumps({"tweets": [], "path": parsed.path}).encode()
        self.send_response(Handler.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TwitterApiIoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.seen = []
        Handler.status = 200
        self.tmp = tempfile.mkdtemp()
        self.kp = os.path.join(self.tmp, "kp.py")
        with open(self.kp, "w") as fh:
            fh.write(FAKE_KP)
        self.kp_args = os.path.join(self.tmp, "kp_args.json")

    def run_it(self, *args, kp_mode="ok"):
        env = dict(os.environ, BRAIN_KP_SCRIPT=self.kp, TWITTERAPI_IO_BASE_URL=self.base,
                   FAKE_KP_ARGS=self.kp_args, FAKE_KP_MODE=kp_mode, FAKE_KP_KEY=KEY)
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                              env=env, timeout=30)

    def test_key_goes_in_the_header_and_never_in_argv(self):
        r = self.run_it("user-info", "dana_example")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Handler.seen[0]["key"], KEY)
        self.assertNotIn(KEY, r.stdout + r.stderr)
        self.assertEqual(json.load(open(self.kp_args)), ["get", "apis/twitterapi-io", "--pipe", "cat"])

    def test_user_tweets_endpoint_and_params(self):
        r = self.run_it("user-tweets", "--username", "sam_example", "--include-replies")
        self.assertEqual(r.returncode, 0, r.stderr)
        seen = Handler.seen[0]
        self.assertEqual(seen["path"], "/twitter/user/last_tweets")
        self.assertEqual(seen["query"]["userName"], "sam_example")
        self.assertEqual(seen["query"]["includeReplies"], "true")
        self.assertNotIn("userId", seen["query"])

    def test_user_tweets_needs_a_user(self):
        r = self.run_it("user-tweets")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(Handler.seen, [])

    def test_search_defaults_to_latest(self):
        r = self.run_it("search", '"solar panels" OR wind')
        self.assertEqual(r.returncode, 0, r.stderr)
        seen = Handler.seen[0]
        self.assertEqual(seen["path"], "/twitter/tweet/advanced_search")
        self.assertEqual(seen["query"]["query"], '"solar panels" OR wind')
        self.assertEqual(seen["query"]["queryType"], "Latest")

    def test_list_timeline_and_tweets_by_ids(self):
        self.run_it("list-timeline", "1234567890")
        self.run_it("tweets-by-ids", "111,222")
        self.assertEqual(Handler.seen[0]["path"], "/twitter/list/tweets_timeline")
        self.assertEqual(Handler.seen[0]["query"]["listId"], "1234567890")
        self.assertEqual(Handler.seen[1]["path"], "/twitter/tweets")
        self.assertEqual(Handler.seen[1]["query"]["tweet_ids"], "111,222")

    def test_response_body_is_printed_raw(self):
        r = self.run_it("user-info", "dana_example")
        self.assertEqual(json.loads(r.stdout)["path"], "/twitter/user/info")

    def test_http_error_is_json_and_exit_1(self):
        Handler.status = 402
        r = self.run_it("user-info", "dana_example")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["_http_error"], 402)

    def test_kp_failure_stops_before_any_request(self):
        r = self.run_it("user-info", "dana_example", kp_mode="fail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("KeePass", r.stderr)
        self.assertEqual(Handler.seen, [])

    def test_empty_key_stops_before_any_request(self):
        r = self.run_it("user-info", "dana_example", kp_mode="empty")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(Handler.seen, [])


def main():
    """unittest, plus the `RESULT: N passed, M failed` line _bin/run_all_tests.py adds up."""
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(TwitterApiIoTest))
    failed = len(result.failures) + len(result.errors)
    print("\nRESULT: %d passed, %d failed" % (result.testsRun - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
