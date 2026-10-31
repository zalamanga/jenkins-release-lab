"""Local configuration and an authenticated, cookie-aware Jenkins API client."""
from __future__ import annotations

import base64
import http.cookiejar
import http.client
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = ("LAB_JENKINS_PASSWORD", "LAB_DB_PASSWORD", "LAB_TEST_DB_PASSWORD", "LAB_ALPHA_API_KEY", "LAB_BETA_API_KEY")
JOB = "reserveflow-release"


def local_opener(base: str):
    def origin(url: str):
        parsed = urllib.parse.urlsplit(url)
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)

    expected = origin(base)
    if expected[0] != 'http' or expected[1] not in {'127.0.0.1', 'localhost', 'controller'}:
        raise ValueError('Only the local lab origin is supported')

    class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, new_url):
            if origin(new_url) != expected:
                raise ValueError('Refusing an authenticated redirect outside the configured lab origin')
            return super().redirect_request(request, fp, code, message, headers, new_url)

    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                      urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                      SameOriginRedirect())


def configuration() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        raise RuntimeError("Run scripts/init_env.py first")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o600)


def assert_no_secrets(data: bytes, values: dict[str, str]) -> None:
    for key in SECRET_KEYS:
        value = values.get(key, "")
        if len(value) >= 24 and value.encode() in data:
            raise RuntimeError(f"Refusing to publish a report containing {key}")


class JenkinsClient:
    def __init__(self, values: dict[str, str], base: str | None = None):
        self.base = (base or values.get("LAB_JENKINS_URL", "http://127.0.0.1:8110/")).rstrip("/") + "/"
        parsed = urllib.parse.urlparse(self.base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "controller"}:
            raise ValueError("Jenkins API client accepts only the local lab controller")
        token = base64.b64encode((values["LAB_JENKINS_USER"] + ":" + values["LAB_JENKINS_PASSWORD"]).encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}
        self.opener = local_opener(self.base)

    def request(self, path: str, data: bytes | None = None, content_type: str = "application/x-www-form-urlencoded") -> tuple[bytes, object]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Expected a controller-relative API path")
        headers = dict(self.headers)
        if data is not None:
            crumb = self.json("/crumbIssuer/api/json")
            headers[crumb["crumbRequestField"]] = crumb["crumb"]
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base.rstrip("/") + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Jenkins request failed: HTTP {error.code} at {urllib.parse.urlsplit(path).path}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise RuntimeError("The local Jenkins controller is not reachable") from None

    def json(self, path: str) -> dict:
        body, _ = self.request(path)
        return json.loads(body)

    def ready(self, timeout: int) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return self.json("/api/json?tree=nodeName,numExecutors,jobs[name]")
            except (RuntimeError, json.JSONDecodeError):
                time.sleep(2)
        raise RuntimeError("Jenkins did not become authenticated and ready within the timeout")
