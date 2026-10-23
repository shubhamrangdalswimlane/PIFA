"""Create the SFTP key pair for files-svc and write it to .env (used by docker compose).

Run: .venv/Scripts/python scripts/dev_keys.py
For Render, paste the printed public key into SFTP_PUBLIC_KEY (pifa-sftp) and the private
key into SFTP_PRIVATE_KEY (pifa-files). The private key is stored with literal "\\n" separators.
"""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Keep the existing .env lines except any previous SFTP key pair.
env = Path(__file__).resolve().parent.parent / ".env"
lines = [ln for ln in (env.read_text().splitlines() if env.exists() else [])
         if not ln.startswith(("SFTP_PUBLIC_KEY=", "SFTP_PRIVATE_KEY="))]

# Generate a new Ed25519 key pair in OpenSSH format.
key = Ed25519PrivateKey.generate()
private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()

# Append both keys (private key on one line with literal "\n") and write .env back.
lines += [f'SFTP_PUBLIC_KEY="{public} files-svc"', f'SFTP_PRIVATE_KEY="{private.strip().replace(chr(10), "\\n")}"']
env.write_text("\n".join(lines) + "\n")
print(f"wrote SFTP keys to {env}\npublic key: {public} files-svc")
