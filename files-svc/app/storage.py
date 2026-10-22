"""File storage on the SFTP server (Render private network), with a local-folder backend for tests."""

import base64
import io
import logging
import os
import posixpath
from contextlib import contextmanager
from pathlib import Path

import paramiko

log = logging.getLogger(__name__)

ROOT = "/files"
FOLDERS = ["inbound/forecast", "inbound/inventory", "inbound/allocation", "processed", "rejected", "outbound"]


def _load_key(text: str) -> paramiko.PKey:
    text = text.replace("\\n", "\n").strip() + "\n"
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text))
        except (paramiko.SSHException, ValueError):
            continue
    raise ValueError("SFTP_PRIVATE_KEY is not a supported private key")


class SftpStorage:
    def __init__(self):
        self.host = os.environ["SFTP_HOST"]
        self.port = int(os.environ.get("SFTP_PORT", "22"))
        self.user = os.environ.get("SFTP_USER", "pifa")
        self.key = _load_key(os.environ["SFTP_PRIVATE_KEY"])
        self.host_key = os.environ.get("SFTP_HOST_KEY", "").strip()  # "ssh-ed25519 AAAA..." to pin

    @contextmanager
    def session(self):
        client = paramiko.SSHClient()
        if self.host_key:
            key_type, key_b64 = self.host_key.split()[:2]
            host = self.host if self.port == 22 else f"[{self.host}]:{self.port}"
            client.get_host_keys().add(host, key_type, paramiko.PKey.from_type_string(key_type, base64.b64decode(key_b64)))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            log.warning("SFTP_HOST_KEY not set: accepting the server key without pinning")
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.host, port=self.port, username=self.user, pkey=self.key, timeout=10,
                       allow_agent=False, look_for_keys=False)
        try:
            yield client.open_sftp()
        finally:
            client.close()

    def put(self, path: str, content: bytes) -> None:
        with self.session() as s:
            s.putfo(io.BytesIO(content), path)

    def get(self, path: str) -> bytes:
        with self.session() as s:
            buf = io.BytesIO()
            s.getfo(path, buf)
            return buf.getvalue()

    def move(self, src: str, dst: str) -> None:
        with self.session() as s:
            s.posix_rename(src, dst)

    def list(self, folder: str) -> list[str]:
        with self.session() as s:
            return sorted(posixpath.join(folder, n) for n in s.listdir(folder) if not n.startswith("."))

    def health(self) -> tuple[bool, str]:
        try:
            with self.session() as s:
                missing = [f for f in FOLDERS if not _exists(s, posixpath.join(ROOT, f))]
            return (not missing, "connected" if not missing else f"missing folders: {missing}")
        except Exception as e:  # noqa: BLE001 - health reports any failure
            return False, str(e)[:200]


def _exists(sftp, path: str) -> bool:
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


class LocalStorage:
    """Same layout under a local folder (STORAGE=local), used by tests and quick local runs."""

    def __init__(self, base: str):
        self.base = Path(base)
        for f in FOLDERS:
            (self.base / ROOT.strip("/") / f).mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        return self.base / path.lstrip("/")

    def put(self, path: str, content: bytes) -> None:
        self._p(path).write_bytes(content)

    def get(self, path: str) -> bytes:
        return self._p(path).read_bytes()

    def move(self, src: str, dst: str) -> None:
        self._p(src).replace(self._p(dst))

    def list(self, folder: str) -> list[str]:
        return sorted(posixpath.join(folder, p.name) for p in self._p(folder).iterdir() if not p.name.startswith("."))

    def health(self) -> tuple[bool, str]:
        return True, f"local storage at {self.base}"


def make_storage():
    if os.environ.get("STORAGE", "sftp") == "local":
        return LocalStorage(os.environ.get("LOCAL_STORAGE_DIR", "./data"))
    return SftpStorage()
