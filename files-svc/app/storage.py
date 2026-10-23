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
    """Load the SFTP client private key from an environment variable value.

    Literal "\\n" sequences are turned into newlines, then Ed25519, ECDSA and RSA formats are tried in turn.

    Args:
        text: The private key in OpenSSH/PEM text form, possibly with literal "\\n" separators.

    Returns:
        The loaded paramiko private key.

    Raises:
        ValueError: When the text is not a supported private key.
    """
    text = text.replace("\\n", "\n").strip() + "\n"
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text))
        except (paramiko.SSHException, ValueError):
            continue
    raise ValueError("SFTP_PRIVATE_KEY is not a supported private key")


class SftpStorage:
    def __init__(self):
        """Read the SFTP connection settings from the environment.

        Uses SFTP_HOST, SFTP_PORT (default 22), SFTP_USER (default "pifa"), SFTP_PRIVATE_KEY and the optional
        SFTP_HOST_KEY ("<type> <base64>") used to pin the server's host key.

        Returns:
            None

        Raises:
            KeyError: When SFTP_HOST or SFTP_PRIVATE_KEY is not set.
            ValueError: When SFTP_PRIVATE_KEY is not a supported private key.
        """
        self.host = os.environ["SFTP_HOST"]
        self.port = int(os.environ.get("SFTP_PORT", "22"))
        self.user = os.environ.get("SFTP_USER", "pifa")
        self.key = _load_key(os.environ["SFTP_PRIVATE_KEY"])
        self.host_key = os.environ.get("SFTP_HOST_KEY", "").strip()  # "ssh-ed25519 AAAA..." to pin

    @contextmanager
    def session(self):
        """Open a short-lived SSH connection and SFTP session, closed when the `with` block ends.

        The server key is checked against SFTP_HOST_KEY when set; otherwise it is accepted with a warning.

        Returns:
            A context manager yielding a paramiko SFTPClient.
        """
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
        """Write a file on the SFTP server, replacing any existing file.

        Args:
            path: Absolute storage path, e.g. "/files/inbound/forecast/x.xlsx".
            content: The file bytes.

        Returns:
            None
        """
        with self.session() as s:
            s.putfo(io.BytesIO(content), path)

    def get(self, path: str) -> bytes:
        """Read a file from the SFTP server.

        Args:
            path: Absolute storage path.

        Returns:
            The file contents as bytes.
        """
        with self.session() as s:
            buf = io.BytesIO()
            s.getfo(path, buf)
            return buf.getvalue()

    def move(self, src: str, dst: str) -> None:
        """Move (rename) a file on the SFTP server, e.g. from inbound to processed/rejected.

        Args:
            src: Current storage path.
            dst: New storage path (overwritten if it exists).

        Returns:
            None
        """
        with self.session() as s:
            s.posix_rename(src, dst)

    def list(self, folder: str) -> list[str]:
        """List the files in a folder on the SFTP server, skipping hidden (dot) files.

        Args:
            folder: Absolute storage folder, e.g. "/files/inbound/forecast".

        Returns:
            Sorted full paths of the entries in the folder.
        """
        with self.session() as s:
            return sorted(posixpath.join(folder, n) for n in s.listdir(folder) if not n.startswith("."))

    def health(self) -> tuple[bool, str]:
        """Check that the SFTP server is reachable and all expected folders exist.

        Returns:
            `(ok, detail)`: `(True, "connected")`, `(False, "missing folders: [...]")`, or `(False, <error text>)`.
        """
        try:
            with self.session() as s:
                missing = [f for f in FOLDERS if not _exists(s, posixpath.join(ROOT, f))]
            return (not missing, "connected" if not missing else f"missing folders: {missing}")
        except Exception as e:  # noqa: BLE001 - health reports any failure
            return False, str(e)[:200]


def _exists(sftp, path: str) -> bool:
    """Tell whether a path exists on the SFTP server.

    Args:
        sftp: An open paramiko SFTPClient.
        path: Absolute storage path.

    Returns:
        True if the path exists, False otherwise.
    """
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


class LocalStorage:
    """Same layout under a local folder (STORAGE=local), used by tests and quick local runs."""

    def __init__(self, base: str):
        """Create the storage folder layout (inbound/*, processed, rejected, outbound) under a local folder.

        Args:
            base: Local folder that stands in for the SFTP server root.

        Returns:
            None
        """
        self.base = Path(base)
        for f in FOLDERS:
            (self.base / ROOT.strip("/") / f).mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        """Map a storage path like "/files/processed/x.xlsx" to the matching local file path.

        Args:
            path: Absolute storage path.

        Returns:
            The local Path under `base`.
        """
        return self.base / path.lstrip("/")

    def put(self, path: str, content: bytes) -> None:
        """Write a file, replacing any existing file.

        Args:
            path: Absolute storage path.
            content: The file bytes.

        Returns:
            None
        """
        self._p(path).write_bytes(content)

    def get(self, path: str) -> bytes:
        """Read a file.

        Args:
            path: Absolute storage path.

        Returns:
            The file contents as bytes.
        """
        return self._p(path).read_bytes()

    def move(self, src: str, dst: str) -> None:
        """Move (rename) a file, overwriting the destination if it exists.

        Args:
            src: Current storage path.
            dst: New storage path.

        Returns:
            None
        """
        self._p(src).replace(self._p(dst))

    def list(self, folder: str) -> list[str]:
        """List the files in a folder, skipping hidden (dot) files.

        Args:
            folder: Absolute storage folder.

        Returns:
            Sorted full storage paths of the entries in the folder.
        """
        return sorted(posixpath.join(folder, p.name) for p in self._p(folder).iterdir() if not p.name.startswith("."))

    def health(self) -> tuple[bool, str]:
        """Report local storage as healthy.

        Returns:
            `(True, "local storage at <base>")`.
        """
        return True, f"local storage at {self.base}"


def make_storage():
    """Pick the storage backend from the STORAGE environment variable.

    Returns:
        A LocalStorage under LOCAL_STORAGE_DIR (default "./data") when STORAGE=local, otherwise an SftpStorage.
    """
    if os.environ.get("STORAGE", "sftp") == "local":
        return LocalStorage(os.environ.get("LOCAL_STORAGE_DIR", "./data"))
    return SftpStorage()
