from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from release_lab.core import LabError
from release_lab.smoke import health, run_smoke


class ContractHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def respond(self):
        if self.server.fail_gateway:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"<html>Bad Gateway</html>")
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        key = self.headers.get("Idempotency-Key")
        token = self.headers.get("Authorization")
        status, data, replayed = 200, {}, False
        if self.path == "/healthz":
            data = {"status": "ok"}
        elif not token:
            status = 401
        elif token == "Bearer beta" and self.path in ("/v1/products/1", "/v1/reservations/2"):
            status = 404
        elif self.path == "/v1/products" and self.command == "POST":
            data, status = {"id": 1}, 201
        elif self.path == "/v1/reservations" and self.command == "POST":
            previous = self.server.keys.get(key)
            if previous and previous != body:
                status = 409
            elif previous:
                data, status, replayed = {"id": 2}, 201, not self.server.break_replay
            elif self.server.keys:
                status = 409
            else:
                self.server.keys[key] = body
                data, status = {"id": 2}, 201
        elif self.path == "/v1/products/1":
            data = {"onHand": 0, "reserved": 0, "available": 0}
        elif self.path == "/v1/audit?limit=100":
            data = {"items": []}
        self.server.requests.append((self.command, self.path, status))
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Lab-Release", "release-1")
        self.send_header("X-Lab-Slot", "blue")
        if replayed:
            self.send_header("Idempotency-Replayed", "true")
        self.end_headers()
        self.wfile.write(raw)


class HTTPContractTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ContractHandler)
        self.server.requests = []
        self.server.keys = {}
        self.server.break_replay = False
        self.server.fail_gateway = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_twelve_real_http_requests_match_upstream_smoke(self):
        evidence = run_smoke(self.base, "alpha", "beta", expected={"release": "release-1", "slot": "blue"})
        self.assertEqual(len(evidence), 12)
        self.assertEqual(len(self.server.requests), 12)
        self.assertEqual([item["status"] for item in evidence], [200, 401, 201, 201, 201, 409, 404, 404, 409, 200, 200, 200])

    def test_http_replay_without_replayed_header_fails(self):
        self.server.break_replay = True
        with self.assertRaises(LabError):
            run_smoke(self.base, "alpha", "beta")
        self.assertEqual(len(self.server.requests), 5)

    def test_proxy_metadata_mismatch_fails_first_request(self):
        with self.assertRaises(LabError):
            run_smoke(self.base, "alpha", "beta", expected={"release": "wrong", "slot": "blue"})
        self.assertEqual(len(self.server.requests), 1)

    def test_health_uses_actual_json_contract(self):
        self.assertTrue(health(self.base))

    def test_real_gateway_failure_preserves_http_status_as_evidence(self):
        self.server.fail_gateway = True
        evidence = []
        with self.assertRaises(LabError):
            run_smoke(self.base, "alpha", "beta", evidence)
        self.assertEqual(evidence[0]["status"], 502)
        self.assertEqual(evidence[0]["path"], "/healthz")
        self.assertFalse(health(self.base))


if __name__ == "__main__":
    unittest.main()
