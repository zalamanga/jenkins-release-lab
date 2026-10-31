from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lab_config import JenkinsClient, local_opener


AUTHORIZATION = "Basic SYNTHETIC-TEST-HEADER"


class RedirectHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.observed.append({"path": self.path,
                                     "authorization": self.headers.get("Authorization"),
                                     "cookie": self.headers.get("Cookie")})
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", self.server.destination)
            self.send_header("Set-Cookie", "synthetic_session=fixture; Path=/")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":"synthetic"}')


class RedirectTests(unittest.TestCase):
    def setUp(self):
        self.origin = self.server()
        self.target = self.server()
        self.base = f"http://127.0.0.1:{self.origin.server_port}"

    def server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        server.observed = []
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self.addCleanup(close)
        return server

    def test_different_port_redirect_never_contacts_target(self):
        self.origin.destination = f"http://127.0.0.1:{self.target.server_port}/target"
        request = urllib.request.Request(self.base + "/redirect", headers={"Authorization": AUTHORIZATION})
        with self.assertRaisesRegex(ValueError, "outside the configured lab origin"):
            local_opener(self.base).open(request, timeout=2)
        self.assertEqual(self.origin.observed[0]["authorization"], AUTHORIZATION)
        self.assertEqual(self.target.observed, [])

    def test_different_hostname_redirect_never_contacts_target(self):
        self.origin.destination = f"http://localhost:{self.target.server_port}/target"
        request = urllib.request.Request(self.base + "/redirect", headers={"Authorization": AUTHORIZATION})
        with self.assertRaisesRegex(ValueError, "outside the configured lab origin"):
            local_opener(self.base).open(request, timeout=2)
        self.assertEqual(self.target.observed, [])

    def test_same_origin_redirect_preserves_authentication_and_session_cookie(self):
        self.origin.destination = self.base + "/target"
        request = urllib.request.Request(self.base + "/redirect", headers={"Authorization": AUTHORIZATION})
        with local_opener(self.base).open(request, timeout=2) as response:
            self.assertEqual(json.load(response), {"result": "synthetic"})
        self.assertEqual([item["path"] for item in self.origin.observed], ["/redirect", "/target"])
        self.assertEqual(self.origin.observed[1]["authorization"], AUTHORIZATION)
        self.assertEqual(self.origin.observed[1]["cookie"], "synthetic_session=fixture")
        self.assertEqual(self.target.observed, [])


class FakeResponse(io.BytesIO):
    headers = {}


class StartupRecoveryTests(unittest.TestCase):
    def client(self):
        return JenkinsClient({"LAB_JENKINS_USER": "synthetic-user",
                              "LAB_JENKINS_PASSWORD": "synthetic-private-fixture"})

    def test_connection_reset_becomes_a_sanitized_public_error(self):
        client = self.client()
        client.opener = Mock()
        client.opener.open.side_effect = ConnectionResetError("synthetic-private-fixture")
        with self.assertRaises(RuntimeError) as caught:
            client.request("/api/json")
        self.assertEqual(str(caught.exception), "The local Jenkins controller is not reachable")
        self.assertNotIn("synthetic-private-fixture", str(caught.exception))

    def test_ready_recovers_after_one_connection_reset(self):
        client = self.client()
        client.opener = Mock()
        expected = {"nodeName": "", "numExecutors": 0, "jobs": []}
        client.opener.open.side_effect = [ConnectionResetError("synthetic startup reset"),
                                          FakeResponse(json.dumps(expected).encode())]
        with patch("lab_config.time.sleep") as sleep:
            self.assertEqual(client.ready(timeout=1), expected)
        self.assertEqual(client.opener.open.call_count, 2)
        sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
