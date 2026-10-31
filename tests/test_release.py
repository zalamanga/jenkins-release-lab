import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from release_lab.core import (Docker, LabError, OWNER, OWNER_KEY, atomic_write,
                              private_env, read_json, state_lock, write_json)
from release_lab.engine import Engine, GATEWAY, PREFIX, nginx_config
from release_lab.junit import go_results, junit_xml


EXPECTED = json.loads((ROOT / "upstream.lock.json").read_text())["expected_tests"]


class ResultTests(unittest.TestCase):
    def output(self, status="PASS"):
        return "\n".join(f"--- {status}: {name} (0.03s)" for name in EXPECTED)

    def test_actual_eight_passes(self):
        report = go_results(self.output(), 0, EXPECTED)
        self.assertTrue(report["passed"])
        xml = ET.fromstring(junit_xml(report))
        self.assertEqual(xml.attrib["tests"], "8")
        self.assertEqual(xml.attrib["failures"], "0")
        self.assertEqual(len(xml.findall("testcase")), 8)

    def test_skip_is_not_a_successful_db_gate(self):
        report = go_results(self.output().replace("PASS", "SKIP", 1), 0, EXPECTED)
        self.assertFalse(report["passed"])
        self.assertEqual(len(ET.fromstring(junit_xml(report)).findall("testcase/skipped")), 1)

    def test_missing_test_is_reported_as_missing(self):
        report = go_results("", 0, EXPECTED)
        self.assertFalse(report["passed"])
        self.assertTrue(all(case["status"] == "MISSING" for case in report["tests"]))

    def test_nonzero_process_overrides_pass_lines(self):
        report = go_results(self.output(), 137, EXPECTED)
        self.assertFalse(report["passed"])
        self.assertEqual(ET.fromstring(junit_xml(report)).attrib["failures"], "1")

    def test_untrusted_stdout_is_never_copied_to_junit(self):
        report = go_results(self.output() + "\npostgres://private-secret@db\n", 0, EXPECTED)
        self.assertNotIn("private-secret", junit_xml(report))
        self.assertNotIn("postgres", json.dumps(report))


class FilesAndSafetyTests(unittest.TestCase):
    def test_private_file_atomic_replace_and_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "app.env"
            private_env(path, {"PASSWORD": "private-value"})
            private_env(path, {"PASSWORD": "changed-value"})
            self.assertEqual(path.read_text(), "PASSWORD=changed-value\n")
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual([p.name for p in path.parent.iterdir()], ["app.env"])

    def test_newline_credential_injection_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(LabError):
                private_env(Path(temporary) / "env", {"PASSWORD": "value\nINJECTED=1"})

    def test_state_lock_is_portable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with state_lock(temporary):
                write_json(Path(temporary) / "state.json", {"active": "one"})
            self.assertEqual(read_json(Path(temporary) / "state.json"), {"active": "one"})

    def test_unowned_container_cannot_be_removed(self):
        docker = Docker()
        with patch.object(docker, "container", return_value={"labels": {}}), patch.object(docker, "run") as run:
            with self.assertRaises(LabError):
                docker.remove("unrelated")
            run.assert_not_called()

    def test_docker_error_redacts_private_stderr_and_argv(self):
        result = subprocess.CompletedProcess([], 1, "private-output", "postgres://secret@db")
        with patch("release_lab.core.subprocess.run", return_value=result):
            with self.assertRaises(LabError) as caught:
                Docker().run("run", "--env", "PASSWORD=secret")
        self.assertEqual(str(caught.exception), "Docker run failed (exit 1)")

    def test_nginx_metadata_is_validated(self):
        with self.assertRaises(LabError):
            nginx_config({"slot": "blue", "release": 'release"; malicious'})
        self.assertIn('X-Lab-Metadata "proxy"', nginx_config({"slot": "blue", "release": "lab-b1"}))


class ReloadDocker:
    def __init__(self):
        self.worker = "10"
        self.replacement = None
        self.overlap = 0
        self.reloads = 0
        self.last_children = {self.worker}
        self.observed_children = []
        self.master = "1"

    def assert_owned(self, name):
        assert name == GATEWAY
        return {"running": True}

    def run(self, *args, **kwargs):
        if args == ("exec", GATEWAY, "cat", "/var/run/nginx.pid"):
            output = self.master + "\n"
        elif args == ("exec", GATEWAY, "cat", "/proc/1/task/1/children"):
            if self.replacement and self.overlap:
                self.last_children = {self.worker, self.replacement}
                self.overlap -= 1
            elif self.replacement:
                self.worker, self.replacement = self.replacement, None
                self.last_children = {self.worker}
            self.observed_children.append(self.last_children.copy())
            output = " ".join(sorted(self.last_children))
        elif args == ("exec", GATEWAY, "nginx", "-s", "reload"):
            self.reloads += 1
            self.replacement = str(int(self.worker) + 1)
            self.overlap = 2
            output = ""
        elif args == ("exec", GATEWAY, "nginx", "-t"):
            output = ""
        else:
            raise AssertionError(f"Unexpected synthetic Docker operation: {args}")
        return subprocess.CompletedProcess(args, 0, output, "")


class GatewayReloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.docker = ReloadDocker()
        self.engine = Engine(ROOT, self.docker, {
            "GIT_COMMIT": "a" * 40, "BUILD_NUMBER": "1", "LAB_STATE_DIR": self.temporary.name})
        self.config = self.engine.directory / "nginx" / "default.conf"
        self.record = {"slot": "green", "release": "lab-green-b2"}
        atomic_write(self.config, nginx_config({"slot": "blue", "release": "lab-blue-b1"}))

    def test_new_metadata_cannot_admit_smoke_while_old_workers_still_serve(self):
        metadata_observations = []

        def new_worker_already_answers(record):
            # HTTP can return the new headers throughout both mixed generations.
            metadata_observations.append(self.docker.last_children.copy())
            return True

        with patch.object(self.engine, "gateway_matches", side_effect=new_worker_already_answers), patch("release_lab.core.time.sleep"):
            self.engine.switch(self.record)
        self.assertIn({"10", "11"}, self.docker.observed_children)
        self.assertEqual(metadata_observations, [{"11"}])
        self.assertEqual(self.docker.reloads, 1)

    def test_failed_metadata_check_restores_config_and_waits_for_recovery_generation(self):
        old = self.config.read_bytes()
        with patch.object(self.engine, "gateway_matches", side_effect=LabError("Synthetic proxy check failed")), patch("release_lab.core.time.sleep"):
            with self.assertRaisesRegex(LabError, "Synthetic proxy check failed"):
                self.engine.switch(self.record)
        self.assertEqual(self.config.read_bytes(), old)
        self.assertEqual(self.docker.reloads, 2)
        self.assertEqual(self.docker.last_children, {"12"})

    def test_invalid_master_pid_stops_before_proc_path_or_reload(self):
        self.docker.master = "1/../../private"
        with self.assertRaisesRegex(LabError, "master process metadata is invalid"):
            self.engine.reload_gateway()
        self.assertEqual(self.docker.reloads, 0)
        self.assertEqual(self.docker.observed_children, [])


class MemoryDocker:
    def __init__(self):
        self.containers = {}
        self.recreated = []
        self.stopped = []
        self.events = []
        self.gateway = None

    def image(self, image):
        return {"image_id": image, "labels": {PREFIX + "release": self.release}}

    def assert_owned(self, name):
        return self.containers.get(name)

    def stop(self, name):
        self.stopped.append(name)
        if name in self.containers:
            self.containers[name]["running"] = False


class SimulatedEngine(Engine):
    def infrastructure(self, credentials):
        pass

    def start_release(self, record, credentials, unhealthy=False):
        self.docker.events.append(("start", record["release"]))
        self.docker.recreated.append(record.copy())
        self.docker.containers[record["container"]] = {
            "id": record["container"] + "-id", "image_id": record["image_id"],
            "running": not unhealthy, "labels": {OWNER_KEY: OWNER, PREFIX + "release": record["release"],
                                                    PREFIX + "slot": record["slot"]}}

    def gate(self, record):
        if not self.selected(record):
            raise LabError("Real health gate simulation failed")

    def switch(self, record):
        self.docker.events.append(("switch", record["release"]))
        self.gateway = record.copy()
        self.docker.gateway = record.copy()

    def gateway_matches(self, record):
        return self.docker.gateway == record and self.selected(record)

    def smoke(self, base, credentials, report_name, expected=None):
        if expected and not self.selected(expected):
            raise LabError("HTTP smoke failed after cutover")
        self.report(report_name, {"passed": True, "request_count": 12})

    def proof(self, state=None):
        gateway = self.docker.gateway or {}
        response = {"status": 200, "release": gateway.get("release"), "slot": gateway.get("slot")}
        with patch("release_lab.engine.request", return_value=response):
            return super().proof(state)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.docker = MemoryDocker()
        self.base_env = {"WORKSPACE": str(self.base / "workspace"), "LAB_STATE_DIR": str(self.base / "lab"),
                         "GIT_COMMIT": "a" * 40, "BUILD_NUMBER": "1", "ACTION": "DEPLOY_GOOD",
                         "LAB_DB_PASSWORD": "db-secret-unique", "LAB_TEST_DB_PASSWORD": "test-secret-unique",
                         "LAB_ALPHA_API_KEY": "a" * 64, "LAB_BETA_API_KEY": "b" * 64}

    def engine(self, build, action="DEPLOY_GOOD"):
        env = dict(self.base_env, BUILD_NUMBER=str(build), ACTION=action)
        engine = SimulatedEngine(ROOT, self.docker, env)
        self.docker.release = engine.release
        if action != "ROLLBACK":
            engine.report("package", {"release": engine.release, "image": "image:" + str(build),
                                       "image_id": "sha256:" + str(build) * 64, "app_commit": engine.lock["commit"],
                                       "lab_commit": env["GIT_COMMIT"], "build": str(build)})
        return engine

    def deploy(self, engine):
        with contextlib.redirect_stdout(io.StringIO()):
            engine.deploy()

    def two_healthy(self):
        first = self.engine(1)
        self.deploy(first)
        one = first.state()["active"]
        second = self.engine(2)
        self.deploy(second)
        return one, second.state()["active"]

    def test_two_healthy_releases_alternate_slots_and_preserve_previous_image(self):
        one, two = self.two_healthy()
        state = self.engine(3).state()
        self.assertEqual((one["slot"], two["slot"]), ("blue", "green"))
        self.assertEqual(state["previous"]["image_id"], one["image_id"])
        self.assertEqual(len(state["history"]), 2)

    def test_unhealthy_candidate_cannot_change_committed_state(self):
        one, two = self.two_healthy()
        bad = self.engine(3, "DEPLOY_UNHEALTHY")
        before = (bad.directory / "state.json").read_bytes()
        with self.assertRaises(LabError):
            self.deploy(bad)
        self.assertEqual((bad.directory / "state.json").read_bytes(), before)
        attempt = read_json(bad.reports / "deployment.json")
        self.assertFalse(attempt["switched"])
        self.assertEqual(read_json(bad.reports / "proof.json")["active"], two)

    def test_rollback_recreates_image_after_previous_slot_overwritten(self):
        one, two = self.two_healthy()
        bad = self.engine(3, "DEPLOY_UNHEALTHY")
        with self.assertRaises(LabError):
            self.deploy(bad)
        self.assertNotEqual(self.docker.containers[one["container"]]["image_id"], one["image_id"])
        rollback = self.engine(4, "ROLLBACK")
        self.deploy(rollback)
        self.assertEqual(rollback.state()["active"], one)
        self.assertEqual(rollback.state()["previous"], two)
        self.assertEqual(self.docker.containers[one["container"]]["image_id"], one["image_id"])
        self.assertEqual(self.docker.recreated[-1]["image_id"], one["image_id"])

    def test_postcutover_fault_recovers_old_gateway_before_error(self):
        one, two = self.two_healthy()
        failed = self.engine(5, "DEPLOY_POSTCHECK_FAIL")
        before = (failed.directory / "state.json").read_bytes()
        with self.assertRaises(LabError):
            self.deploy(failed)
        self.assertEqual(failed.gateway, two)
        self.assertTrue(failed.selected(two))
        self.assertEqual((failed.directory / "state.json").read_bytes(), before)
        attempt = read_json(failed.reports / "deployment.json")
        self.assertTrue(attempt["switched"])
        self.assertTrue(attempt["recovered"])
        self.assertEqual(attempt["status"], "FAILED")

    def test_proof_hashes_actual_committed_state_bytes(self):
        one, two = self.two_healthy()
        engine = self.engine(3, "DEPLOY_UNHEALTHY")
        state_path = engine.directory / "state.json"
        # Whitespace changes bytes without changing the JSON object.
        state_path.write_bytes(state_path.read_bytes() + b"\n  \n")
        before = hashlib.sha256(state_path.read_bytes()).hexdigest()
        self.assertEqual(engine.proof()["state_sha256"], before)
        with self.assertRaises(LabError):
            self.deploy(engine)
        self.assertEqual(read_json(engine.reports / "proof.json")["state_sha256"], before)

    def test_interrupted_gateway_is_reconciled_before_inactive_slot_is_replaced(self):
        one, two = self.two_healthy()
        self.docker.gateway = one
        self.docker.events.clear()
        failed = self.engine(3, "DEPLOY_UNHEALTHY")
        with self.assertRaises(LabError):
            self.deploy(failed)
        self.assertEqual(self.docker.events[0], ("switch", two["release"]))
        self.assertEqual(self.docker.events[1], ("start", failed.release))
        self.assertEqual(self.docker.gateway, two)

    def test_no_previous_rollback_fails_without_claiming_success(self):
        rollback = self.engine(1, "ROLLBACK")
        with self.assertRaises(LabError):
            self.deploy(rollback)
        self.assertIsNone(rollback.state()["active"])
        self.assertEqual(read_json(rollback.reports / "deployment.json")["status"], "FAILED")

    def test_secret_scanner_blocks_credentials_and_unexpected_reports(self):
        engine = self.engine(1)
        engine.report("proof", {"leak": self.base_env["LAB_DB_PASSWORD"]})
        with self.assertRaises(LabError):
            engine.audit_reports()
        engine.report("proof", {"active": None})
        engine.report("unexpected", {})
        with self.assertRaises(LabError):
            engine.audit_reports()
        (engine.reports / "unexpected.json").unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            engine.audit_reports()


if __name__ == "__main__":
    unittest.main()
