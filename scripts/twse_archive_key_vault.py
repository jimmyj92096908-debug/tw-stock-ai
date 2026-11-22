"""Owner-local AES archive key vault with an independently copied recovery file.

The 256-bit archive key exists only transiently in process memory. At rest it
is AES-256-GCM-encrypted with a strong password-derived Scrypt key. Init is
exclusive-create and requires a *second* private path for a recovery copy.
NEVER commit vaults, passwords or presigned URLs. The operator must store the
second copy on independently controlled media and retain the password too;
software cannot prove physical independence.

This tool never talks to Neon, GitHub Actions, LINE, or any market source.
"""
from __future__ import annotations

import argparse
import getpass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets

VERSION = 1
AAD = b"tw-stock-ai/offline-private-archive-key-vault/v1"
SUFFIX = ".twsekey"
MAX_FILE_BYTES = 4096
N = 2**15
R = 8
P = 1


def _password_bytes(password):
    if type(password) is not str or len(password) < 16:
        raise ValueError("Use a private passphrase of at least 16 characters")
    secret = password.encode("utf-8")
    if len(secret) > 1024:
        raise ValueError("Vault passphrase too long")
    return secret


def _private_new_path(path):
    original = Path(path).expanduser()
    if original.is_symlink():
        raise ValueError("Symlinked key custody files are prohibited")
    p = original.resolve()
    if p.suffix != SUFFIX or not p.parent.is_dir() or p.exists():
        raise ValueError("An unused .twsekey path in an existing private directory is required")
    if any((ancestor / ".git").exists() for ancestor in (p.parent, *p.parents)):
        raise ValueError("Vault may not be created inside a Git repository")
    return p


def _private_existing_path(path):
    original = Path(path).expanduser()
    if original.is_symlink():
        raise ValueError("Symlinked key custody files are prohibited")
    p = original.resolve()
    if (not p.is_file() or p.suffix != SUFFIX
            or p.stat().st_size > MAX_FILE_BYTES
            or any((a / ".git").exists() for a in (p.parent, *p.parents))):
        raise ValueError("A small owner-local private vault outside Git is required")
    return p


def _derive(password, salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=N, r=R, p=P).derive(
        _password_bytes(password)
    )


def _encode_vault(key, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if type(key) is not bytes or len(key) != 32:
        raise ValueError("32 random key bytes required")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(_derive(password, salt)).encrypt(nonce, key, AAD)
    doc = {
        "format": "TWSE-ARCHIVE-OFFLINE-KEY-VAULT",
        "version": VERSION,
        "kdf": "scrypt",
        "n": N, "r": R, "p": P,
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "ciphertext": encrypted.hex(),
        "archive_key_length_bits": 256,
    }
    return (json.dumps(doc, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _open_vault(blob, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not isinstance(blob, bytes) or not 0 < len(blob) <= MAX_FILE_BYTES:
        raise ValueError("Invalid bounded private vault")
    try:
        value = json.loads(blob)
        if (type(value) is not dict
                or set(value) != {
                    "format", "version", "kdf", "n", "r", "p",
                    "salt", "nonce", "ciphertext", "archive_key_length_bits",
                }
                or value["format"] != "TWSE-ARCHIVE-OFFLINE-KEY-VAULT"
                or type(value["version"]) is not int or value["version"] != VERSION
                or value["kdf"] != "scrypt"
                or type(value["n"]) is not int or value["n"] != N
                or type(value["r"]) is not int or value["r"] != R
                or type(value["p"]) is not int or value["p"] != P
                or value["archive_key_length_bits"] != 256):
            raise ValueError("Invalid key vault metadata")
        for name, expected_length in (("salt", 32), ("nonce", 24), ("ciphertext", 96)):
            v = value[name]
            if (type(v) is not str or len(v) != expected_length
                    or any(c not in "0123456789abcdef" for c in v)):
                raise ValueError("Invalid key vault encoding")
        salt = bytes.fromhex(value["salt"])
        nonce = bytes.fromhex(value["nonce"])
        ct = bytes.fromhex(value["ciphertext"])
        key = AESGCM(_derive(password, salt)).decrypt(nonce, ct, AAD)
        if len(key) != 32:
            raise ValueError("Invalid decrypted archive key")
    except Exception:
        # The caller must never receive passwords or key material on failure.
        raise ValueError("Vault password incorrect or vault integrity damaged") from None
    return key


def _write_once(p, blob):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    handle = os.open(p, flags, 0o600)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(blob)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        # An exclusive-create write may fail halfway through the file.
        Path(p).unlink(missing_ok=True)
        raise


def initialize_vault(*, vault_path, recovery_path, passphrase):
    """Make one key with two identical password-encrypted recovery files."""
    _password_bytes(passphrase)
    vault = _private_new_path(vault_path)
    recovery = _private_new_path(recovery_path)
    if vault == recovery or vault.parent == recovery.parent:
        raise ValueError("The recovery copy must be in a separate directory")
    # Never use a key generated by public CI for a production archive.
    secret = secrets.token_bytes(32)
    encrypted = _encode_vault(secret, passphrase)
    made = []
    try:
        _write_once(vault, encrypted)
        made.append(vault)
        _write_once(recovery, encrypted)
        made.append(recovery)
        if (vault.read_bytes() != recovery.read_bytes()
                or _open_vault(vault.read_bytes(), passphrase) != secret
                or _open_vault(recovery.read_bytes(), passphrase) != secret):
            raise ValueError("Independent recovery copy failed integrity check")
    except BaseException:
        # Do not leave an unrecoverable single half-created key behind.
        for p in made:
            p.unlink(missing_ok=True)
        raise
    return {
        "scope": "OWNER_OFFLINE_ARCHIVE_VAULT_INITIALIZED",
        "two_identical_private_encrypted_copies_verified": True,
        "file_sha256": sha256(encrypted).hexdigest(),
        "archive_key_printed": False,
        "passphrase_printed": False,
        "independent_physical_media_verified_by_software": False,
        "production_archive_uploaded": False,
        "neon_price_rows_modified": 0,
        "line_messages_sent": 0,
    }


def verify_vault(*, vault_path, recovery_path, passphrase):
    """Verify independent ciphertext copies and the actual decryption key."""
    primary = _private_existing_path(vault_path)
    backup = _private_existing_path(recovery_path)
    if primary == backup:
        raise ValueError("Distinct encrypted key custody files required")
    a = primary.read_bytes()
    b = backup.read_bytes()
    if a != b:
        raise ValueError("Primary and recovery key custody files differ")
    first = _open_vault(a, passphrase)
    second = _open_vault(b, passphrase)
    if first != second:
        raise ValueError("Archive keys recovered from the two vaults differ")
    return {
        "scope": "OWNER_OFFLINE_ARCHIVE_VAULT_RECOVERY_VERIFIED",
        "two_private_copies_decrypt_to_same_key": True,
        "file_sha256": sha256(a).hexdigest(),
        "archive_key_printed": False,
        "passphrase_printed": False,
        "physical_media_independence_not_proven": True,
        "production_archive_uploaded": False,
    }


def load_archive_key_hex(vault_path, *, passphrase=None):
    """Load only in owner-local process memory, not stdout or GitHub outputs."""
    if passphrase is None:
        passphrase = getpass.getpass("Private archive vault passphrase: ")
    p = _private_existing_path(vault_path)
    return _open_vault(p.read_bytes(), passphrase).hex()


def resolve_archive_key(*, vault_path=None, env_key=None):
    """Vault mode and transient env key mode are mutually exclusive."""
    if vault_path and env_key:
        raise ValueError("Specify either --key-vault or STOCK_ARCHIVE_KEY_HEX, not both")
    if vault_path:
        return load_archive_key_hex(vault_path)
    if env_key:
        from scripts.twse_local_encrypted_archive import _key
        _key(env_key)
        return env_key
    raise ValueError("An owner-controlled private archive AES key is required")


def main():
    cli = argparse.ArgumentParser(description="Owner-local TWSE AES archive key custody")
    cli.add_argument("action", choices=("init", "verify"))
    cli.add_argument("--vault", type=Path, required=True)
    cli.add_argument("--recovery", type=Path, required=True)
    opts = cli.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        cli.error("Never generate or verify owner archive keys on public CI")
    try:
        pwd = getpass.getpass("Private vault passphrase (>=16 chars): ")
        if opts.action == "init":
            if pwd != getpass.getpass("Confirm vault passphrase: "):
                raise ValueError("Vault passphrase confirmation mismatch")
            result = initialize_vault(
                vault_path=opts.vault, recovery_path=opts.recovery,
                passphrase=pwd,
            )
        else:
            result = verify_vault(
                vault_path=opts.vault, recovery_path=opts.recovery,
                passphrase=pwd,
            )
    except Exception:
        raise SystemExit("Private key custody verification failed; no secret printed") from None
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
