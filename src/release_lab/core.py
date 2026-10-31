import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


OWNER_KEY = "io.jenkins-release-lab.owner"
OWNER = "jenkins-release-lab"
LABEL = f"{OWNER_KEY}={OWNER}"


class LabError(RuntimeError):
    """A public, credential-free failure reason."""


def atomic_write(path, content, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            if private:
                os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if private:
            os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


@contextlib.contextmanager
def state_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".release.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            stream.write(b"0")
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def private_env(path, values):
    for key, value in values.items():
        if not isinstance(value, str) or any(c in value for c in "\r\n\x00"):
            raise LabError("Credential format is invalid")
        if not key.replace("_", "").isalnum():
            raise LabError("Environment key is invalid")
    atomic_write(path, "".join(f"{key}={value}\n" for key, value in values.items()), private=True)
    return Path(path)


class Docker:
    def run(self, *args, check=True, timeout=180, input_text=None):
        # Docker stderr can contain credentials. Only operation names leave this boundary.
        operation = args[0] if args else "command"
        try:
            result = subprocess.run(["docker", *map(str, args)], input=input_text,
                                    text=True, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise LabError(f"Docker {operation} did not complete") from None
        if check and result.returncode:
            raise LabError(f"Docker {operation} failed (exit {result.returncode})")
        return result

    def container(self, name):
        fmt = '{{json .Id}}\n{{json .Image}}\n{{json .State.Running}}\n{{json .Config.Labels}}'
        result = self.run("inspect", "--type", "container", "--format", fmt, name, check=False)
        if result.returncode:
            return None
        try:
            cid, image, running, labels = map(json.loads, result.stdout.splitlines())
            return {"id": cid, "image_id": image, "running": running, "labels": labels or {}}
        except (ValueError, TypeError):
            raise LabError("Container metadata could not be read") from None

    def image(self, name):
        result = self.run("image", "inspect", "--format", '{{json .Id}}\n{{json .Config.Labels}}', name)
        try:
            image, labels = map(json.loads, result.stdout.splitlines())
            return {"image_id": image, "labels": labels or {}}
        except (ValueError, TypeError):
            raise LabError("Image metadata could not be read") from None

    def assert_owned(self, name):
        item = self.container(name)
        if item and item["labels"].get(OWNER_KEY) != OWNER:
            raise LabError("Refusing to mutate a container outside this lab")
        return item

    def remove(self, name):
        if self.assert_owned(name):
            self.run("rm", "--force", name)

    def stop(self, name):
        if self.assert_owned(name):
            self.run("stop", "--time", "8", name)

    def ensure_resource(self, kind, name):
        result = self.run(kind, "inspect", "--format", '{{json .Labels}}', name, check=False)
        if result.returncode == 0:
            if (json.loads(result.stdout) or {}).get(OWNER_KEY) != OWNER:
                raise LabError(f"Refusing to use an unowned {kind}")
        else:
            self.run(kind, "create", "--label", LABEL, name)


def wait_until(predicate, seconds=60, interval=1):
    deadline = time.monotonic() + seconds
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise LabError("Bounded health gate timed out")
        time.sleep(interval)
