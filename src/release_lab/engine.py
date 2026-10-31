import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from .core import (Docker, LABEL, OWNER, OWNER_KEY, LabError, atomic_write,
                   private_env, read_json, state_lock, wait_until, write_json)
from .junit import go_results, junit_xml
from .smoke import health, request, run_smoke


NETWORK = "jenkins-release-lab-net"
DATABASE = "jenkins-release-lab-db"
VOLUME = "jenkins-release-lab-pgdata"
GATEWAY = "jenkins-release-lab-gateway"
SLOTS = {"blue": 18081, "green": 18082}
PREFIX = "io.jenkins-release-lab."
ACTIONS = {"DEPLOY_GOOD", "DEPLOY_UNHEALTHY", "ROLLBACK", "DEPLOY_POSTCHECK_FAIL"}


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def nginx_config(record):
    if record["slot"] not in SLOTS or not re.fullmatch(r"[a-zA-Z0-9_.-]+", record["release"]):
        raise LabError("Invalid proxy release metadata")
    return f'''server {{
    listen 8080;
    server_name _;
    add_header X-Lab-Release "{record['release']}" always;
    add_header X-Lab-Slot "{record['slot']}" always;
    add_header X-Lab-Metadata "proxy" always;
    location / {{
        proxy_pass http://jenkins-release-lab-{record['slot']}:8080;
        proxy_connect_timeout 2s;
        proxy_read_timeout 10s;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }}
}}
'''


class Engine:
    def __init__(self, root=None, docker=None, env=None):
        self.env = dict(os.environ if env is None else env)
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self.workspace = Path(self.env.get("WORKSPACE", self.root))
        self.directory = Path(self.env.get("LAB_STATE_DIR", "/lab"))
        self.reports = self.workspace / "reports"
        self.upstream = self.root / ".local" / "upstream"
        self.lock = read_json(self.root / "upstream.lock.json")
        self.versions = read_json(self.root / "versions.lock.json", {})
        self.docker = docker or Docker()
        self.action = self.env.get("ACTION", "DEPLOY_GOOD")
        if self.action not in ACTIONS:
            raise LabError("Unknown release action")
        self.commit = self.env.get("GIT_COMMIT", "")
        self.build = self.env.get("BUILD_NUMBER", "")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", self.commit):
            raise LabError("GIT_COMMIT must identify the lab checkout")
        if not re.fullmatch(r"[0-9]+", self.build):
            raise LabError("BUILD_NUMBER must be numeric")
        self.release = f"lab-{self.commit[:12].lower()}-b{self.build}"

    def image_name(self, kind):
        images = self.versions.get("images", {})
        value = images.get(kind)
        if isinstance(value, dict):
            value = value.get("image") or value.get("reference")
        if not value:
            raise LabError(f"versions.lock.json does not pin {kind}")
        return value

    def report(self, name, value):
        write_json(self.reports / (name + ".json"), value)

    def state(self):
        return read_json(self.directory / "state.json", {"schema": 1, "active": None,
                                                         "previous": None, "history": []})

    def credentials(self, test=False):
        names = ["LAB_TEST_DB_PASSWORD"] if test else ["LAB_DB_PASSWORD", "LAB_ALPHA_API_KEY", "LAB_BETA_API_KEY"]
        values = {}
        for name in names:
            value = self.env.get(name, "")
            if not value or any(c in value for c in "\r\n\x00"):
                raise LabError("Required private credentials are unavailable")
            if name.endswith("API_KEY") and not re.fullmatch(r"[a-fA-F0-9]{64}", value):
                raise LabError("Tenant keys must contain 64 hexadecimal characters")
            values[name] = value
        if not test and values["LAB_ALPHA_API_KEY"] == values["LAB_BETA_API_KEY"]:
            raise LabError("Tenant keys must differ")
        return values

    def verify_upstream(self):
        import subprocess
        try:
            result = subprocess.run(["git", "-C", str(self.upstream), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, timeout=20, check=True)
            dirty = subprocess.run(["git", "-C", str(self.upstream), "status", "--porcelain"],
                                   capture_output=True, text=True, timeout=20, check=True)
        except (OSError, subprocess.SubprocessError):
            raise LabError("Pinned upstream checkout is unavailable") from None
        if result.stdout.strip() != self.lock["commit"] or dirty.stdout.strip():
            raise LabError("Upstream checkout differs from upstream.lock.json")

    def build_image(self, target, tag):
        self.verify_upstream()
        self.docker.run("build", "--target", target, "--tag", tag,
                        "--label", LABEL,
                        "--label", f"{PREFIX}release={self.release}",
                        "--label", f"{PREFIX}lab-revision={self.commit}",
                        "--label", f"{PREFIX}upstream-revision={self.lock['commit']}",
                        "--label", f"{PREFIX}build={self.build}",
                        "--label", f"org.opencontainers.image.revision={self.commit}",
                        "--label", f"org.opencontainers.image.version={self.release}",
                        "--label", "org.opencontainers.image.title=ReserveFlow Jenkins deployment lab",
                        str(self.upstream), timeout=1200)

    def test(self):
        secret = self.credentials(test=True)["LAB_TEST_DB_PASSWORD"]
        tag = f"jenkins-release-lab-tests:{self.release}"
        self.build_image(self.lock["tests_target"], tag)
        self.docker.ensure_resource("network", NETWORK)
        suffix = self.build + "-" + self.commit[:8].lower()
        db = f"jenkins-release-lab-test-db-{suffix}"
        runner = f"jenkins-release-lab-test-run-{suffix}"
        private = self.directory / "private"
        pg_env = private_env(private / f"test-db-{suffix}.env", {
            "POSTGRES_PASSWORD": secret, "POSTGRES_DB": "reserveflow_test", "POSTGRES_USER": "reserveflow"})
        dsn = f"postgres://reserveflow:{urllib.parse.quote(secret, safe='')}@{db}:5432/reserveflow_test?sslmode=disable"
        test_env = private_env(private / f"test-run-{suffix}.env", {
            "RESERVEFLOW_TEST_DATABASE_URL": dsn, "REQUIRE_DB_TESTS": "1"})
        result = None
        try:
            self.docker.remove(runner)
            self.docker.remove(db)
            self.docker.run("run", "--detach", "--name", db, "--label", LABEL,
                            "--network", NETWORK, "--memory", "256m", "--cpus", "1",
                            "--tmpfs", "/var/lib/postgresql/data:rw,size=256m",
                            "--env-file", pg_env, self.image_name("postgres"), timeout=900)
            self.wait_database(db, "reserveflow_test")
            result = self.docker.run("run", "--name", runner, "--label", LABEL,
                                     "--network", NETWORK, "--memory", "192m", "--cpus", "1",
                                     "--env-file", test_env, tag, check=False, timeout=150)
            parsed = go_results(result.stdout, result.returncode, self.lock["expected_tests"])
            parsed.update({"recorded_at": now(), "upstream_commit": self.lock["commit"],
                           "database": "reserveflow_test", "ephemeral_database": True})
            self.report("tests", parsed)
            atomic_write(self.reports / "test-results.xml", junit_xml(parsed))
            if not parsed["passed"]:
                raise LabError("Actual Go/PostgreSQL tests failed or did not all execute")
            print(f"Actual Go/PostgreSQL tests passed: {len(parsed['tests'])}")
        finally:
            self.docker.remove(runner)
            self.docker.remove(db)
            pg_env.unlink(missing_ok=True)
            test_env.unlink(missing_ok=True)

    def package(self):
        image = f"jenkins-release-lab-api:{self.release}"
        self.build_image(self.lock["runtime_target"], image)
        metadata = self.docker.image(image)
        self.report("package", {"release": self.release, "image": image,
                                "image_id": metadata["image_id"], "app_commit": self.lock["commit"],
                                "lab_commit": self.commit, "build": self.build, "recorded_at": now()})
        print("Packaged immutable deployment version " + self.release)

    def wait_database(self, name=DATABASE, database="reserveflow"):
        def ready():
            try:
                return self.docker.run("exec", name, "pg_isready", "--quiet", "--host", "127.0.0.1", "--username",
                                       "reserveflow", "--dbname", database, check=False, timeout=8).returncode == 0
            except LabError:
                return False

        wait_until(ready, seconds=60)

    def infrastructure(self, credentials):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.docker.ensure_resource("network", NETWORK)
        self.docker.ensure_resource("volume", VOLUME)
        existing = self.docker.assert_owned(DATABASE)
        if existing:
            if not existing["running"]:
                self.docker.run("start", DATABASE)
        else:
            env_file = private_env(self.directory / "private" / "database.env", {
                "POSTGRES_PASSWORD": credentials["LAB_DB_PASSWORD"],
                "POSTGRES_DB": "reserveflow", "POSTGRES_USER": "reserveflow"})
            self.docker.run("run", "--detach", "--name", DATABASE, "--label", LABEL,
                            "--network", NETWORK, "--restart", "unless-stopped",
                            "--memory", "256m", "--cpus", "1", "--env-file", env_file,
                            "--mount", f"type=volume,source={VOLUME},target=/var/lib/postgresql/data",
                            self.image_name("postgres"), timeout=900)
        self.wait_database()

    def start_release(self, record, credentials, unhealthy=False):
        name = record["container"]
        self.docker.remove(name)
        port = "1" if unhealthy else "5432"
        dsn = (f"postgres://reserveflow:{urllib.parse.quote(credentials['LAB_DB_PASSWORD'], safe='')}"
               f"@{DATABASE}:{port}/reserveflow?sslmode=disable")
        env_file = private_env(self.directory / "private" / (record["slot"] + ".env"), {
            "DATABASE_URL": dsn,
            "ALPHA_KEY_SHA256": hashlib.sha256(credentials["LAB_ALPHA_API_KEY"].encode()).hexdigest(),
            "BETA_KEY_SHA256": hashlib.sha256(credentials["LAB_BETA_API_KEY"].encode()).hexdigest()})
        self.docker.run("run", "--detach", "--name", name, "--label", LABEL,
                        "--label", f"{PREFIX}release={record['release']}",
                        "--label", f"{PREFIX}slot={record['slot']}",
                        "--network", NETWORK, "--memory", "128m", "--cpus", "1",
                        "--env-file", env_file, "--publish", f"0.0.0.0:{SLOTS[record['slot']]}:8080",
                        record["image_id"])

    def selected(self, record):
        item = self.docker.assert_owned(record["container"])
        return bool(item and item["running"] and item["image_id"] == record["image_id"]
                    and item["labels"].get(PREFIX + "release") == record["release"]
                    and item["labels"].get(PREFIX + "slot") == record["slot"])

    def ensure_release(self, record, credentials):
        # The inactive slot may have been overwritten by a failed candidate.
        if not self.selected(record):
            self.start_release(record, credentials)
        self.gate(record)

    def gate(self, record):
        wait_until(lambda: self.selected(record) and health(self.direct_url(record)), seconds=45)

    def direct_url(self, record):
        return f"http://engine:{SLOTS[record['slot']]}"

    def nginx_workers(self):
        master = self.docker.run("exec", GATEWAY, "cat", "/var/run/nginx.pid", timeout=8).stdout.strip()
        if not re.fullmatch(r"[1-9][0-9]*", master):
            raise LabError("Gateway master process metadata is invalid")
        output = self.docker.run("exec", GATEWAY, "cat", f"/proc/{master}/task/{master}/children",
                                 timeout=8).stdout.split()
        if any(not re.fullmatch(r"[1-9][0-9]*", pid) for pid in output):
            raise LabError("Gateway worker process metadata is invalid")
        return master, set(output)

    def reload_gateway(self):
        self.docker.run("exec", GATEWAY, "nginx", "-t")
        master, previous = self.nginx_workers()
        if not previous:
            raise LabError("Gateway has no worker generation before reload")
        self.docker.run("exec", GATEWAY, "nginx", "-s", "reload")

        def old_workers_exited():
            current_master, current = self.nginx_workers()
            if current_master != master:
                raise LabError("Gateway master changed during configuration reload")
            return bool(current) and previous.isdisjoint(current)

        # A new worker can answer while old workers still serve the previous config.
        wait_until(old_workers_exited, seconds=15, interval=0.1)

    def switch(self, record):
        config = self.directory / "nginx" / "default.conf"
        old = config.read_text(encoding="utf-8") if config.exists() else None
        atomic_write(config, nginx_config(record))
        existing = self.docker.assert_owned(GATEWAY)
        try:
            if existing:
                if not existing["running"]:
                    self.docker.run("start", GATEWAY)
                self.reload_gateway()
            else:
                main_config = self.directory / "nginx-main.conf"
                atomic_write(main_config, "worker_processes 1;\npid /var/run/nginx.pid;\n"
                             "events { worker_connections 128; }\n"
                             "http { access_log off; include /etc/nginx/conf.d/*.conf; }\n")
                self.docker.run("run", "--detach", "--name", GATEWAY, "--label", LABEL,
                                "--network", NETWORK, "--restart", "unless-stopped",
                                "--memory", "64m", "--cpus", "0.5",
                                "--publish", "0.0.0.0:8080:8080",
                                "--mount", f"type=bind,source={config.parent},target=/etc/nginx/conf.d,readonly",
                                "--mount", f"type=bind,source={main_config},target=/etc/nginx/nginx.conf,readonly",
                                self.image_name("nginx"), timeout=900)
                self.docker.run("exec", GATEWAY, "nginx", "-t")
            wait_until(lambda: self.gateway_matches(record), seconds=15, interval=0.25)
        except LabError:
            if old is not None:
                atomic_write(config, old)
                if self.docker.assert_owned(GATEWAY):
                    try:
                        self.reload_gateway()
                    except LabError:
                        pass
            raise

    def gateway_matches(self, record):
        try:
            result = request("http://engine:8080", "GET", "/healthz")
            return (result["status"] == 200 and result["release"] == record["release"]
                    and result["slot"] == record["slot"])
        except LabError:
            return False

    def smoke(self, base, credentials, report_name, expected=None):
        evidence = []
        report = {"recorded_at": now(), "passed": False, "requests": evidence}
        try:
            run_smoke(base, credentials["LAB_ALPHA_API_KEY"], credentials["LAB_BETA_API_KEY"], evidence, expected)
            report["passed"] = True
        finally:
            report["request_count"] = len(evidence)
            self.report(report_name, report)
        return report

    def proof(self, state=None):
        state = state or self.state()
        active = state.get("active")
        state_path = self.directory / "state.json"
        state_hash = hashlib.sha256(state_path.read_bytes()).hexdigest() if state_path.exists() else None
        proof = {"recorded_at": now(), "active": active, "metadata_source": "nginx proxy headers",
                 "state_sha256": state_hash,
                 "container": None, "gateway": {"healthy": False}}
        if active:
            item = self.docker.assert_owned(active["container"])
            if item:
                proof["container"] = {"id": item["id"], "image_id": item["image_id"],
                                       "running": item["running"],
                                       "release": item["labels"].get(PREFIX + "release"),
                                       "slot": item["labels"].get(PREFIX + "slot")}
            try:
                gateway = request("http://engine:8080", "GET", "/healthz")
                proof["gateway"] = {"healthy": gateway["status"] == 200,
                                     "status": gateway["status"], "release": gateway["release"],
                                     "slot": gateway["slot"]}
            except LabError:
                pass
        self.report("proof", proof)
        return proof

    def deployment_record(self, slot):
        package = read_json(self.reports / "package.json")
        if not package or package["release"] != self.release:
            raise LabError("This build has no packaged release")
        metadata = self.docker.image(package["image_id"])
        if metadata["labels"].get(PREFIX + "release") != self.release:
            raise LabError("Packaged image metadata does not match this build")
        return {key: package[key] for key in ("release", "image", "image_id", "app_commit", "lab_commit", "build")} | {
            "slot": slot, "container": "jenkins-release-lab-" + slot}

    def append_attempt(self, attempt):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "deployment-history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(attempt, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def deploy(self):
        credentials = self.credentials()
        with state_lock(self.directory):
            state = self.state()
            old = state.get("active")
            attempt = {"recorded_at": now(), "action": self.action, "build": self.build,
                       "lab_commit": self.commit, "status": "FAILED", "switched": False,
                       "recovered": False, "before": old, "candidate": None}
            candidate = None
            switched = False
            try:
                self.infrastructure(credentials)
                if old:
                    self.ensure_release(old, credentials)
                    if not self.gateway_matches(old):
                        self.switch(old)
                if self.action == "ROLLBACK":
                    candidate = state.get("previous")
                    if not candidate:
                        raise LabError("No previous healthy release is available")
                    if old and candidate["slot"] == old["slot"]:
                        raise LabError("Previous release has an invalid active slot")
                    attempt["candidate"] = candidate
                    self.ensure_release(candidate, credentials)
                else:
                    slot = "green" if old and old["slot"] == "blue" else "blue"
                    candidate = self.deployment_record(slot)
                    attempt["candidate"] = candidate
                    self.start_release(candidate, credentials, unhealthy=self.action == "DEPLOY_UNHEALTHY")
                    self.gate(candidate)
                self.smoke(self.direct_url(candidate), credentials, "candidate-smoke")
                self.switch(candidate)
                switched = True
                attempt["switched"] = True
                if self.action == "DEPLOY_POSTCHECK_FAIL":
                    self.docker.stop(candidate["container"])
                    attempt["fault"] = "candidate stopped after proxy switch"
                self.smoke("http://engine:8080", credentials, "smoke", expected=candidate)
                if not self.selected(candidate):
                    raise LabError("Selected container changed before state commit")
                event = {"recorded_at": now(), "action": self.action, "build": self.build,
                         "release": candidate["release"], "slot": candidate["slot"]}
                committed = {"schema": 1, "active": candidate, "previous": old,
                             "history": state.get("history", []) + [event]}
                write_json(self.directory / "state.json", committed)
                attempt["status"] = "SUCCESS"
                attempt["after"] = candidate
                self.proof(committed)
                print(f"Release selected: {candidate['release']} ({candidate['slot']})")
            except LabError as error:
                attempt["reason"] = str(error)
                if switched and old:
                    self.ensure_release(old, credentials)
                    self.switch(old)
                    self.smoke("http://engine:8080", credentials, "recovery-smoke", expected=old)
                    attempt["recovered"] = True
                if candidate and (not old or candidate["container"] != old["container"]):
                    self.docker.stop(candidate["container"])
                self.proof(state)
                raise
            finally:
                self.report("deployment", attempt)
                self.append_attempt(attempt)

    def post(self):
        credentials = self.credentials()
        with state_lock(self.directory):
            state = self.state()
            active = state.get("active")
            if not active or not self.selected(active):
                raise LabError("No selected healthy release exists")
            self.smoke("http://engine:8080", credentials, "postcheck", expected=active)
            self.proof(state)
        print("Gateway post-check passed: 12 real HTTP requests")

    def status(self):
        with state_lock(self.directory):
            print(json.dumps({"state": self.state(), "proof": self.proof()}, sort_keys=True))

    def audit_reports(self):
        allowed = {"tests.json", "test-results.xml", "package.json", "deployment.json",
                   "candidate-smoke.json", "smoke.json", "recovery-smoke.json",
                   "proof.json", "postcheck.json"}
        secrets = [self.env.get(name, "") for name in (
            "LAB_DB_PASSWORD", "LAB_TEST_DB_PASSWORD", "LAB_ALPHA_API_KEY", "LAB_BETA_API_KEY")]
        if any(not secret for secret in secrets):
            raise LabError("All four credential bindings are required to audit reports")
        for path in self.reports.glob("*"):
            if path.suffix not in (".json", ".xml"):
                continue
            if not path.is_file() or path.is_symlink() or path.name not in allowed:
                raise LabError("Unexpected public report artifact")
            content = path.read_text(encoding="utf-8")
            if any(value in content for secret in secrets
                   for value in (secret, urllib.parse.quote(secret, safe=""))):
                raise LabError("A report contains private credential material; archive blocked")
            if re.search(r"postgres(?:ql)?://|Bearer\s+[a-zA-Z0-9]{32,}", content):
                raise LabError("A report contains private connection material; archive blocked")
            try:
                json.loads(content) if path.suffix == ".json" else ET.fromstring(content)
            except (ValueError, ET.ParseError):
                raise LabError("A public report is malformed") from None
        print("Public report credential scan passed")
