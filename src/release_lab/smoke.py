import json
import urllib.error
import urllib.request
import uuid

from .core import LabError


def request(base, method, path, body=None, key=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data, headers, method=method)
    try:
        try:
            response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=8)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            text = response.read(1024 * 1024).decode("utf-8")
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            return {"status": response.status, "text": text, "data": data,
                    "replayed": response.headers.get("Idempotency-Replayed") == "true",
                    "release": response.headers.get("X-Lab-Release"),
                    "slot": response.headers.get("X-Lab-Slot")}
    except (OSError, ValueError, urllib.error.URLError):
        raise LabError("HTTP request failed") from None


def health(base):
    try:
        result = request(base, "GET", "/healthz")
        return (result["status"] == 200 and isinstance(result["data"], dict)
                and result["data"].get("status") == "ok")
    except LabError:
        return False


def run_smoke(base, alpha, beta, evidence=None, expected=None):
    evidence = evidence if evidence is not None else []
    suffix = uuid.uuid4().hex[:12].upper()

    def call(method, path, status, body=None, key=None, token=alpha):
        try:
            result = request(base, method, path, body, key, token)
        except LabError:
            evidence.append({"method": method, "path": path, "status": None,
                             "expected_status": status, "replayed": False, "request_failed": True})
            raise
        evidence.append({"method": method, "path": path, "status": result["status"],
                         "expected_status": status, "replayed": result["replayed"]})
        if result["status"] != status:
            raise LabError(f"HTTP smoke contract failed at request {len(evidence)}")
        if not isinstance(result["data"], dict):
            raise LabError("HTTP smoke received an invalid JSON response")
        if expected and (result["release"] != expected["release"] or result["slot"] != expected["slot"]):
            raise LabError("Proxy metadata does not match the selected release")
        return result

    call("GET", "/healthz", 200, token=None)
    call("GET", "/v1/products", 401, token=None)
    product = call("POST", "/v1/products", 201,
                   {"sku": "SMOKE-" + suffix, "name": "Synthetic smoke stock", "onHand": 1})["data"]
    payload = {"productId": product["id"], "quantity": 1, "ttlSeconds": 60}
    held = call("POST", "/v1/reservations", 201, payload, "hold-" + suffix)
    replay = call("POST", "/v1/reservations", 201, payload, "hold-" + suffix)
    if held["text"] != replay["text"] or not replay["replayed"]:
        raise LabError("Idempotency replay contract failed")
    call("POST", "/v1/reservations", 409, dict(payload, quantity=2), "hold-" + suffix)
    call("GET", f'/v1/reservations/{held["data"]["id"]}', 404, token=beta)
    call("GET", f'/v1/products/{product["id"]}', 404, token=beta)
    call("POST", "/v1/reservations", 409, payload, "another-" + suffix)
    call("POST", f'/v1/reservations/{held["data"]["id"]}/confirm', 200, {}, "confirm-" + suffix)
    current = call("GET", f'/v1/products/{product["id"]}', 200)["data"]
    if any(current.get(key) != 0 for key in ("onHand", "reserved", "available")):
        raise LabError("Stock confirmation contract failed")
    audit = call("GET", "/v1/audit?limit=100", 200)["data"]
    if not isinstance(audit.get("items"), list):
        raise LabError("Audit response contract failed")
    return evidence
