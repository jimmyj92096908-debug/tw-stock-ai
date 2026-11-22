"""Owner-local encrypted AES key vault: no secrets printed or sent over network."""
from pathlib import Path
import json
import os
import secrets
import stat
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.twse_archive_key_vault import (
    _open_vault, initialize_vault, load_archive_key_hex,
    resolve_archive_key, verify_vault,
)


class ArchiveKeyVaultTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.left = self.parent / "owner-vault"
        self.right = self.parent / "independent-copy"
        self.left.mkdir()
        self.right.mkdir()
        self.primary = self.left / "history.twsekey"
        self.recovery = self.right / "history.twsekey"
        self.pwd = "correct horse battery staple independent offline key"

    def _make(self):
        return initialize_vault(
            vault_path=self.primary, recovery_path=self.recovery,
            passphrase=self.pwd,
        )

    def test_initialized_recovery_copies_match_without_exposing_secret(self):
        receipt = self._make()
        self.assertTrue(receipt["two_identical_private_encrypted_copies_verified"])
        self.assertFalse(receipt["independent_physical_media_verified_by_software"])
        self.assertFalse(receipt["archive_key_printed"])
        self.assertEqual(self.primary.read_bytes(), self.recovery.read_bytes())
        doc = json.loads(self.primary.read_text())
        self.assertEqual(doc["kdf"], "scrypt")
        self.assertEqual(doc["n"], 2**15)
        self.assertEqual(doc["archive_key_length_bits"], 256)
        self.assertNotIn(self.pwd, self.primary.read_text())
        self.assertNotIn("STOCK_ARCHIVE_KEY_HEX", self.primary.read_text())
        first = load_archive_key_hex(self.primary, passphrase=self.pwd)
        second = load_archive_key_hex(self.recovery, passphrase=self.pwd)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn(first, self.primary.read_text())
        self.assertNotIn(first, str(receipt))
        restored = verify_vault(
            vault_path=self.primary, recovery_path=self.recovery,
            passphrase=self.pwd,
        )
        self.assertTrue(restored["two_private_copies_decrypt_to_same_key"])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.primary.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.recovery.stat().st_mode), 0o600)

    def test_wrong_password_tamper_and_mismatched_copies_fail_closed(self):
        self._make()
        with self.assertRaises(ValueError):
            load_archive_key_hex(self.primary, passphrase="not the correct phrase")
        damaged = bytearray(self.recovery.read_bytes())
        # Corrupt the authenticated encrypted key, not just file metadata.
        doc = json.loads(damaged)
        doc["ciphertext"] = "0" * 96
        self.recovery.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            verify_vault(
                vault_path=self.primary, recovery_path=self.recovery,
                passphrase=self.pwd,
            )
        with self.assertRaises(ValueError):
            load_archive_key_hex(self.recovery, passphrase=self.pwd)

    def test_second_init_does_not_overwrite_existing_owner_keys(self):
        self._make()
        original = self.primary.read_bytes()
        with self.assertRaises(ValueError):
            self._make()
        self.assertEqual(self.primary.read_bytes(), original)

    def test_key_creation_rejects_git_path_and_same_folder(self):
        with self.assertRaises(ValueError):
            initialize_vault(
                vault_path=self.primary,
                recovery_path=self.left / "copy.twsekey",
                passphrase=self.pwd,
            )
        self.assertFalse(self.primary.exists())
        (self.right / ".git").mkdir()
        with self.assertRaises(ValueError):
            self._make()
        self.assertFalse(self.primary.exists())

    def test_missing_recovery_copy_fails_verification(self):
        self._make()
        self.recovery.unlink()
        with self.assertRaises(ValueError):
            verify_vault(
                vault_path=self.primary, recovery_path=self.recovery,
                passphrase=self.pwd,
            )

    def test_symlink_and_weak_password_rejected_before_file_write(self):
        for password in ("", "short", "123456789012345"):
            with self.subTest(length=len(password)), self.assertRaises(ValueError):
                initialize_vault(
                    vault_path=self.primary, recovery_path=self.recovery,
                    passphrase=password,
                )
        self.assertFalse(self.primary.exists())
        try:
            self.primary.symlink_to(self.right / "not-real.twsekey")
        except (OSError, NotImplementedError):
            return
        with self.assertRaises(ValueError):
            self._make()

    def test_owner_process_resolver_never_exposes_key_in_cli(self):
        self._make()
        with patch("scripts.twse_archive_key_vault.getpass.getpass",
                   return_value=self.pwd) as getpass:
            key = resolve_archive_key(vault_path=self.primary, env_key="")
        self.assertEqual(len(key), 64)
        getpass.assert_called_once()
        with self.assertRaises(ValueError):
            resolve_archive_key(vault_path=self.primary, env_key=secrets.token_hex(32))
        with self.assertRaises(ValueError):
            resolve_archive_key(vault_path=None, env_key="")
        with self.assertRaises(ValueError):
            resolve_archive_key(vault_path=None, env_key="abc")

    def test_recovery_file_creation_failure_cleans_both_half_copies(self):
        from scripts import twse_archive_key_vault as target
        original = target._write_once
        def fail_on_copy(path, blob):
            if Path(path) == self.recovery:
                raise OSError("simulated copy failure")
            return original(path, blob)
        with patch.object(target, "_write_once", side_effect=fail_on_copy):
            with self.assertRaises(OSError):
                self._make()
        self.assertFalse(self.primary.exists())
        self.assertFalse(self.recovery.exists())

    def test_vault_password_not_accepted_from_short_or_untrusted_metadata(self):
        self._make()
        bad = json.loads(self.primary.read_text())
        bad["n"] = 2**24
        with self.assertRaises(ValueError):
            _open_vault(json.dumps(bad).encode(), self.pwd)
