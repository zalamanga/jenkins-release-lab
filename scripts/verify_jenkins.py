"""Exercise real Jenkins jobs, HTTP traffic, immutable images and data persistence."""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from lab_config import ROOT, JOB, JenkinsClient, assert_no_secrets, configuration, local_opener

SCENARIOS = (("DEPLOY_GOOD", "SUCCESS"), ("DEPLOY_GOOD", "SUCCESS"),
             ("DEPLOY_UNHEALTHY", "FAILURE"), ("ROLLBACK", "SUCCESS"),
             ("DEPLOY_POSTCHECK_FAIL", "FAILURE"))


def api(values: dict, method: str, path: str, body: dict | None = None) -> dict:
    headers = {"Authorization": "Bearer " + values["LAB_ALPHA_API_KEY"], "Content-Type": "application/json"}
    request = urllib.request.Request("http://127.0.0.1:8111" + path,
                                     None if body is None else json.dumps(body).encode(), headers, method=method)
    try:
        with local_opener('http://127.0.0.1:8111').open(request, timeout=20) as response:
            return {"status": response.status, "data": json.load(response), "release": response.headers.get("X-Lab-Release"), "slot": response.headers.get("X-Lab-Slot")}
    except (urllib.error.URLError, ValueError):
        raise RuntimeError("The local API gateway did not return a successful JSON response") from None


def trigger(client: JenkinsClient, action: str, timeout: int) -> dict:
    _, headers = client.request(f"/job/{JOB}/buildWithParameters", urllib.parse.urlencode({"ACTION": action}).encode())
    location = headers.get("Location", "")
    path = urllib.parse.urlparse(location).path
    if not re.fullmatch(r"/queue/item/\d+/", path):
        raise RuntimeError("Jenkins did not identify the submitted queue item")
    deadline = time.monotonic() + timeout
    number = None
    while time.monotonic() < deadline:
        item = client.json(path + "api/json")
        if item.get("cancelled"):
            raise RuntimeError("Jenkins cancelled the requested lab build")
        if item.get("executable"):
            number = item["executable"]["number"]
            break
        time.sleep(2)
    if number is None:
        raise RuntimeError("The requested lab job did not leave the queue")
    print(f"Jenkins build {number}: {action} started", flush=True)
    while time.monotonic() < deadline:
        build = client.json(f"/job/{JOB}/{number}/api/json?tree=number,building,result,duration,url,artifacts[relativePath]")
        if not build["building"]:
            return build
        time.sleep(3)
    raise RuntimeError("The requested Jenkins build did not finish within the timeout")


def artifact(client: JenkinsClient, number: int, name: str, values: dict) -> dict:
    raw, _ = client.request(f"/job/{JOB}/{number}/artifact/reports/{name}.json")
    assert_no_secrets(raw, values)
    return json.loads(raw)


def assert_active(proof: dict) -> dict:
    active = proof.get("active")
    container = proof.get("container")
    gateway = proof.get("gateway", {})
    if not active or not container or not container["running"] or not gateway.get("healthy"):
        raise RuntimeError("No running release was proven through both container and gateway")
    for key in ("release", "slot"):
        if active[key] != container[key] or active[key] != gateway[key]:
            raise RuntimeError("Proxy, container and committed release do not agree")
    if active["image_id"] != container["image_id"]:
        raise RuntimeError("The selected container does not use the committed immutable image")
    if not re.fullmatch(r"[a-f0-9]{64}", proof.get("state_sha256") or ""):
        raise RuntimeError("The committed state fingerprint is absent")
    return active


def verify(timeout: int) -> dict:
    values = configuration()
    client = JenkinsClient(values)
    controller = client.ready(60)
    node = client.json("/computer/builder/api/json?tree=offline,temporarilyOffline,numExecutors")
    if controller["numExecutors"] != 0 or node["numExecutors"] != 1 or node["offline"]:
        raise RuntimeError("Expected an idle controller and one connected build executor")
    _, response_headers = client.request("/login")
    report = {"schema_version": 1, "result": "PASS", "job": JOB,
              "jenkins_version": response_headers.get("X-Jenkins"),
              "controller_executors": 0, "agent_executors": 1,
              "upstream_commit": json.loads((ROOT / "upstream.lock.json").read_text())["commit"],
              "runs": [], "checks": {}}
    first = second = rollback = None
    sentinel = None
    for index, (action, expected) in enumerate(SCENARIOS):
        build = trigger(client, action, timeout)
        number = build["number"]
        if build["result"] != expected:
            console, _ = client.request(f"/job/{JOB}/{number}/consoleText")
            assert_no_secrets(console, values)
            print(console.decode('utf-8', errors='replace')[-6000:], flush=True)
            raise RuntimeError(f"Jenkins build {number} returned {build['result']}; expected {expected}")
        proof = artifact(client, number, "proof", values)
        deployment = artifact(client, number, "deployment", values)
        active = assert_active(proof)
        if active["app_commit"] != report["upstream_commit"]:
            raise RuntimeError("Deployed application source differs from the immutable upstream lock")
        if re.fullmatch(r"[a-f0-9]{40}", values["LAB_GIT_REF"]) and deployment["lab_commit"] != values["LAB_GIT_REF"]:
            raise RuntimeError("Jenkins did not execute the intended lab source revision")
        run = {"number": number, "action": action, "result": build["result"],
               "duration_ms": build["duration"], "deployment": deployment,
               "proof": proof, "tests": None, "smoke_probes": {}}
        if expected == 'SUCCESS':
            for probe in ('candidate-smoke', 'smoke', 'postcheck'):
                result = artifact(client, number, probe, values)
                if not result['passed'] or result['request_count'] != 12:
                    raise RuntimeError('A successful release did not record all twelve requests in each smoke probe')
                run['smoke_probes'][probe] = {'passed': True, 'requests': result['requests']}
        if action != "ROLLBACK":
            tests = client.json(f"/job/{JOB}/{number}/testReport/api/json?tree=passCount,failCount,skipCount")
            counts = {key: tests.get(key) for key in ("passCount", "failCount", "skipCount")}
            if counts != {"passCount": 8, "failCount": 0, "skipCount": 0}:
                raise RuntimeError("Unexpected Jenkins JUnit counts: " + json.dumps(counts))
            run["tests"] = {"totalCount": sum(counts.values()), **counts}
        health = api(values, "GET", "/healthz")
        if health["status"] != 200 or health["data"].get("status") != "ok" or health["release"] != active["release"] or health["slot"] != active["slot"]:
            raise RuntimeError("Host-observed traffic differs from the Jenkins proof")
        if index == 0:
            first = proof
            created = api(values, "POST", "/v1/products", {"sku": "PERSIST-" + uuid.uuid4().hex[:12].upper(), "name": "Synthetic release persistence marker", "onHand": 17})
            if created["status"] != 201:
                raise RuntimeError("Persistence marker was not created")
            sentinel = created["data"]["id"]
        elif index == 1:
            second = proof
            if active["release"] == first["active"]["release"] or active["slot"] == first["active"]["slot"] or active["image_id"] == first["active"]["image_id"]:
                raise RuntimeError("The second successful build did not select a new slot and image")
        elif index == 2:
            if proof["active"] != second["active"] or proof["state_sha256"] != second["state_sha256"] or deployment["switched"]:
                raise RuntimeError("Unhealthy candidate changed committed state or received selected traffic")
            report["checks"]["unhealthy_candidate_preserved_active"] = True
        elif index == 3:
            rollback = proof
            if active != first["active"]:
                raise RuntimeError("Manual rollback did not recreate the first immutable release")
            report["checks"]["manual_rollback_restored_original_image"] = True
        elif index == 4:
            failed_smoke = artifact(client, number, "smoke", values)
            recovered_smoke = artifact(client, number, "recovery-smoke", values)
            if not deployment["switched"] or not deployment["recovered"] or proof["active"] != rollback["active"] or proof["state_sha256"] != rollback["state_sha256"]:
                raise RuntimeError("Post-cutover failure did not restore the committed release and exact state")
            failed_status = failed_smoke["requests"][0]["status"]
            if failed_smoke["passed"] or failed_status not in {502, 504} or not recovered_smoke["passed"]:
                raise RuntimeError("Unexpected post-cutover HTTP evidence: " + json.dumps({
                    "failed_status": failed_status, "failed_probe_passed": failed_smoke["passed"],
                    "recovery_probe_passed": recovered_smoke["passed"]}))
            report["checks"]["post_cutover_failure_recovered"] = True
            run["failed_http_status"] = failed_status
            run["recovery_request_count"] = recovered_smoke["request_count"]
            candidate_smoke = artifact(client, number, 'candidate-smoke', values)
            if not candidate_smoke['passed'] or candidate_smoke['request_count'] != 12 or recovered_smoke['request_count'] != 12:
                raise RuntimeError('Candidate and recovery smoke evidence is incomplete')
            run['smoke_probes'] = {'candidate-smoke': candidate_smoke, 'smoke': failed_smoke, 'recovery-smoke': recovered_smoke}
        marker = api(values, "GET", f"/v1/products/{sentinel}")["data"]
        if marker.get("onHand") != 17 or marker.get("available") != 17:
            raise RuntimeError("Deployment or rollback changed the persistent synthetic marker")
        run["persistence_marker_preserved"] = True
        report["runs"].append(run)
        print(f"Jenkins build {number}: verified {expected}; active {active['release']} ({active['slot']})", flush=True)
    report["checks"]["data_persisted_across_all_five_builds"] = True
    report["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = (json.dumps(report, indent=2) + "\n").encode()
    assert_no_secrets(payload, values)
    (ROOT / ".local").mkdir(exist_ok=True)
    (ROOT / ".local/verification.json").write_bytes(payload)
    print("PASS: five real Jenkins builds, health gates, exact-image rollback, automatic recovery and persistent data.", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=1800, help="Maximum seconds for each actual Jenkins build")
    args = parser.parse_args()
    try:
        verify(args.timeout)
    except Exception as error:
        # Only our short public errors are emitted; HTTP payloads and credentials stay private.
        message = str(error) if isinstance(error, RuntimeError) else "Unexpected verification failure; inspect local controller state"
        print("Verification failed: " + message)
        raise SystemExit(1)
