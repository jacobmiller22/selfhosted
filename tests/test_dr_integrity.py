#!/usr/bin/env python3
"""
Unit tests validating Disaster Recovery (DR) Multi-Database Integrity Suite.
Covers tools/backup-dr/verify-db-integrity.sh:
- CLI argument parsing and error handling
- SQLite PRAGMA integrity_check and PRAGMA foreign_key_check assertions
- Actual Budget account, user databases, and sync blobs
- Vaultwarden database, users/ciphers counts, 0600 key permissions, and storage
- Home Assistant database integrity and .storage/* JSON registry syntax
- Nginx Proxy Manager database and Let's Encrypt certificate inspection
- PostgreSQL dump headers and table count assertions
- Structured exit codes across all error scenarios
"""

import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "backup-dr" / "verify-db-integrity.sh"
SHELL_TEST_PATH = REPO_ROOT / "tools" / "backup-dr" / "test-dr-integrity.sh"


class BaseDRIntegrityTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_dr_integrity_")
        self.sandbox = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_verify(self, args: list[str], check_returncode: bool = False) -> subprocess.CompletedProcess:
        cmd = [str(SCRIPT_PATH)] + args
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        if check_returncode and res.returncode != 0:
            raise AssertionError(f"Command {' '.join(cmd)} failed with {res.returncode}:\n{res.stderr}\n{res.stdout}")
        return res

    def create_sqlite_db(self, db_path: Path, sql_script: str):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(db_path))
        con.executescript(sql_script)
        con.close()

    def generate_rsa_key(self, key_path: Path, mode: int = 0o600):
        key_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["openssl", "genrsa", "-out", str(key_path), "2048"],
            capture_output=True,
            check=True,
        )
        os.chmod(str(key_path), mode)

    def generate_self_signed_cert(self, cert_path: Path, key_path: Path):
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key_path), "-out", str(cert_path),
                "-days", "30", "-subj", "/CN=cloud.jacobmiller22.com"
            ],
            capture_output=True,
            check=True,
        )


class TestDRIntegrityCLI(BaseDRIntegrityTestCase):
    def test_scripts_exist_and_are_executable(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"{SCRIPT_PATH} must exist")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")
        self.assertTrue(SHELL_TEST_PATH.exists(), f"{SHELL_TEST_PATH} must exist")
        self.assertTrue(os.access(SHELL_TEST_PATH, os.X_OK), f"{SHELL_TEST_PATH} must be executable")

    def test_cli_help_flags(self):
        for flag in ["-h", "--help"]:
            res = self.run_verify([flag])
            self.assertEqual(res.returncode, 0, f"Flag {flag} must exit 0")
            self.assertIn("Usage:", res.stdout)
            self.assertIn("--service", res.stdout)
            self.assertIn("--dir", res.stdout)
            self.assertIn("--file", res.stdout)
            self.assertIn("--verbose", res.stdout)
            self.assertIn("Exit Codes:", res.stdout)

    def test_cli_missing_arguments(self):
        # Running with no parameters
        res = self.run_verify([])
        self.assertEqual(res.returncode, 1)
        self.assertIn("Either --dir <path> or --file <path> must be specified", res.stderr)

        # Missing value for flag
        res = self.run_verify(["--service"])
        self.assertEqual(res.returncode, 1)
        self.assertIn("Missing value", res.stderr)

        # Unknown option
        res = self.run_verify(["--unknown-flag"])
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unknown option", res.stderr)

        # Target directory does not exist
        res = self.run_verify(["--dir", str(self.sandbox / "nonexistent")])
        self.assertEqual(res.returncode, 1)
        self.assertIn("Target directory does not exist", res.stderr)

        # Target file does not exist
        res = self.run_verify(["--file", str(self.sandbox / "missing.db")])
        self.assertEqual(res.returncode, 1)
        self.assertIn("Target file does not exist", res.stderr)


class TestActualBudgetIntegrity(BaseDRIntegrityTestCase):
    def _setup_valid_actual(self) -> Path:
        act_dir = self.sandbox / "actual"
        (act_dir / "server-files").mkdir(parents=True)
        (act_dir / "user-files").mkdir(parents=True)

        # Primary account.sqlite
        self.create_sqlite_db(
            act_dir / "server-files" / "account.sqlite",
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE users (id TEXT PRIMARY KEY, user_name TEXT);
            INSERT INTO users VALUES ('usr_1', 'admin@example.com');
            """
        )

        # User budget db
        self.create_sqlite_db(
            act_dir / "user-files" / "budget_primary.sqlite",
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE transactions (id TEXT PRIMARY KEY, acct_id TEXT REFERENCES accounts(id), amount INT);
            INSERT INTO accounts VALUES ('acct_1', 'Checking');
            INSERT INTO transactions VALUES ('tx_1', 'acct_1', -2500);
            """
        )

        # Sync blob
        (act_dir / "user-files" / "sync.blob").write_bytes(b"mock_actual_sync_blob_payload")
        return act_dir

    def test_valid_actual_backup(self):
        act_dir = self._setup_valid_actual()
        res = self.run_verify(["--service", "actual", "--dir", str(act_dir), "--verbose"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Actual Budget integrity and sanity validation SUCCEEDED", res.stdout)
        self.assertIn("1 users registered", res.stdout)
        self.assertIn("sync blobs verified", res.stdout.lower())

    def test_account_db_zero_users(self):
        act_dir = self._setup_valid_actual()
        con = sqlite3.connect(str(act_dir / "server-files" / "account.sqlite"))
        con.execute("DELETE FROM users;")
        con.commit()
        con.close()
        res = self.run_verify(["--service", "actual", "--dir", str(act_dir)])
        self.assertEqual(res.returncode, 4)
        self.assertIn("user sanity check FAILED", res.stderr)

    def test_foreign_key_violation_in_user_db(self):
        act_dir = self._setup_valid_actual()
        # Insert orphan transaction with non-existent account
        con = sqlite3.connect(str(act_dir / "user-files" / "budget_primary.sqlite"))
        con.execute("PRAGMA foreign_keys = OFF;")
        con.execute("INSERT INTO transactions VALUES ('tx_orphan', 'ghost_acct', 500);")
        con.commit()
        con.close()

        res = self.run_verify(["--service", "actual", "--dir", str(act_dir)])
        self.assertEqual(res.returncode, 3)
        self.assertIn("foreign key constraint check FAILED", res.stderr)

    def test_missing_sync_blobs(self):
        act_dir = self._setup_valid_actual()
        (act_dir / "user-files" / "sync.blob").unlink()

        res = self.run_verify(["--service", "actual", "--dir", str(act_dir)])
        self.assertEqual(res.returncode, 6)
        self.assertIn("No .blob sync files found", res.stderr)

    def test_empty_sync_blob(self):
        act_dir = self._setup_valid_actual()
        (act_dir / "user-files" / "sync.blob").write_bytes(b"")

        res = self.run_verify(["--service", "actual", "--dir", str(act_dir)])
        self.assertEqual(res.returncode, 6)
        self.assertIn("is empty (0 bytes)", res.stderr)


class TestVaultwardenIntegrity(BaseDRIntegrityTestCase):
    def _setup_valid_vaultwarden(self) -> Path:
        vw_dir = self.sandbox / "vaultwarden"
        (vw_dir / "attachments").mkdir(parents=True)
        (vw_dir / "sends").mkdir(parents=True)

        self.create_sqlite_db(
            vw_dir / "db.sqlite3",
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE users (uuid TEXT PRIMARY KEY, email TEXT);
            CREATE TABLE ciphers (uuid TEXT PRIMARY KEY, user_uuid TEXT REFERENCES users(uuid), notes TEXT);
            INSERT INTO users VALUES ('u-1', 'admin@example.com');
            INSERT INTO ciphers VALUES ('c-1', 'u-1', 'vault-cipher-payload');
            """
        )

        self.generate_rsa_key(vw_dir / "rsa_key.pem", mode=0o600)
        return vw_dir

    def test_valid_vaultwarden_backup(self):
        vw_dir = self._setup_valid_vaultwarden()
        res = self.run_verify(["--service", "vaultwarden", "--dir", str(vw_dir), "--verbose"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Vaultwarden integrity and sanity validation SUCCEEDED", res.stdout)
        self.assertIn("1 users, 1 ciphers", res.stdout)
        self.assertIn("rsa_key.pem validated cleanly", res.stdout)

    def test_zero_users_in_vaultwarden(self):
        vw_dir = self._setup_valid_vaultwarden()
        con = sqlite3.connect(str(vw_dir / "db.sqlite3"))
        con.execute("DELETE FROM ciphers;")
        con.execute("DELETE FROM users;")
        con.commit()
        con.close()
        res = self.run_verify(["--service", "vaultwarden", "--dir", str(vw_dir)])
        self.assertEqual(res.returncode, 4)
        self.assertIn("Vaultwarden users sanity check FAILED", res.stderr)

    def test_foreign_key_violation_in_vaultwarden(self):
        vw_dir = self._setup_valid_vaultwarden()
        con = sqlite3.connect(str(vw_dir / "db.sqlite3"))
        con.execute("PRAGMA foreign_keys = OFF;")
        con.execute("INSERT INTO ciphers VALUES ('c-orphan', 'nonexistent-user', 'data');")
        con.commit()
        con.close()
        res = self.run_verify(["--service", "vaultwarden", "--dir", str(vw_dir)])
        self.assertEqual(res.returncode, 3)
        self.assertIn("foreign key constraint check FAILED", res.stderr)

    def test_rsa_key_permissive_permissions(self):
        vw_dir = self._setup_valid_vaultwarden()
        os.chmod(str(vw_dir / "rsa_key.pem"), 0o644)

        res = self.run_verify(["--service", "vaultwarden", "--dir", str(vw_dir)])
        self.assertEqual(res.returncode, 5)
        self.assertIn("rsa_key.pem permissions check FAILED", res.stderr)

    def test_corrupt_rsa_key(self):
        vw_dir = self._setup_valid_vaultwarden()
        (vw_dir / "rsa_key.pem").write_text("NOT_A_VALID_RSA_KEY\n", encoding="utf-8")
        os.chmod(str(vw_dir / "rsa_key.pem"), 0o600)

        res = self.run_verify(["--service", "vaultwarden", "--dir", str(vw_dir)])
        self.assertEqual(res.returncode, 5)
        self.assertIn("failed OpenSSL cryptographic validation", res.stderr)

    def test_missing_storage_directories(self):
        vw_dir = self._setup_valid_vaultwarden()
        shutil.rmtree(str(vw_dir / "sends"))

        res = self.run_verify(["--service", "vaultwarden", "--dir", str(vw_dir)])
        self.assertEqual(res.returncode, 6)
        self.assertIn("sends directory missing", res.stderr)


class TestHomeAssistantIntegrity(BaseDRIntegrityTestCase):
    def _setup_valid_ha(self) -> Path:
        ha_dir = self.sandbox / "homeassistant"
        (ha_dir / ".storage").mkdir(parents=True)

        self.create_sqlite_db(
            ha_dir / "home-assistant_v2.db",
            """
            CREATE TABLE states (state_id INTEGER PRIMARY KEY, entity_id TEXT, state TEXT);
            INSERT INTO states VALUES (1, 'sensor.living_room_temp', '68.5');
            """
        )

        (ha_dir / ".storage" / "core.config").write_text('{"version": 1, "data": {"latitude": 40.0}}', encoding="utf-8")
        (ha_dir / ".storage" / "auth").write_text('{"version": 1, "data": {"users": []}}', encoding="utf-8")
        return ha_dir

    def test_valid_homeassistant_backup(self):
        ha_dir = self._setup_valid_ha()
        res = self.run_verify(["--service", "homeassistant", "--dir", str(ha_dir), "--verbose"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Home Assistant integrity and sanity validation SUCCEEDED", res.stdout)
        self.assertIn("2 JSON files validated", res.stdout)

    def test_malformed_json_registry(self):
        ha_dir = self._setup_valid_ha()
        (ha_dir / ".storage" / "broken.json").write_text('{"key": "broken", unclosed: true', encoding="utf-8")

        res = self.run_verify(["--service", "homeassistant", "--dir", str(ha_dir)])
        self.assertEqual(res.returncode, 7)
        self.assertIn("JSON syntax error", res.stderr)

    def test_missing_storage_directory(self):
        ha_dir = self._setup_valid_ha()
        shutil.rmtree(str(ha_dir / ".storage"))

        res = self.run_verify(["--service", "homeassistant", "--dir", str(ha_dir)])
        self.assertEqual(res.returncode, 7)
        self.assertIn(".storage directory missing", res.stderr)


class TestNPMIntegrity(BaseDRIntegrityTestCase):
    def _setup_valid_npm(self) -> Path:
        npm_dir = self.sandbox / "npm"
        (npm_dir / "letsencrypt").mkdir(parents=True)

        self.create_sqlite_db(
            npm_dir / "database.sqlite",
            """
            CREATE TABLE proxy_host (id INTEGER PRIMARY KEY, domain_names TEXT, forward_host TEXT);
            INSERT INTO proxy_host VALUES (1, '["app.example.com"]', 'app_upstream');
            """
        )

        self.generate_self_signed_cert(
            npm_dir / "letsencrypt" / "cert.pem",
            npm_dir / "letsencrypt" / "privkey.pem",
        )
        return npm_dir

    def test_valid_npm_backup(self):
        npm_dir = self._setup_valid_npm()
        res = self.run_verify(["--service", "npm", "--dir", str(npm_dir), "--verbose"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Nginx Proxy Manager integrity and sanity validation SUCCEEDED", res.stdout)
        self.assertIn("1 valid certificates", res.stdout)

    def test_invalid_certificate_in_npm(self):
        npm_dir = self._setup_valid_npm()
        (npm_dir / "letsencrypt" / "corrupt.pem").write_text(
            "-----BEGIN CERTIFICATE-----\nCORRUPT_BASE64_DATA\n-----END CERTIFICATE-----\n",
            encoding="utf-8"
        )
        res = self.run_verify(["--service", "npm", "--dir", str(npm_dir)])
        self.assertEqual(res.returncode, 5)
        self.assertIn("NPM certificate validation FAILED", res.stderr)


class TestPostgreSQLIntegrity(BaseDRIntegrityTestCase):
    def test_valid_postgres_dump(self):
        pg_dir = self.sandbox / "postgres"
        pg_dir.mkdir(parents=True)
        dump_file = pg_dir / "dump.sql"
        dump_file.write_text(
            """--
-- PostgreSQL database dump
-- Dumped by pg_dump version 16.1
--
SET statement_timeout = 0;
CREATE TABLE cluster_nodes (id SERIAL PRIMARY KEY, hostname VARCHAR(255));
CREATE TABLE audit_log (id BIGSERIAL PRIMARY KEY, event TEXT);
INSERT INTO cluster_nodes (hostname) VALUES ('bjorn');
-- PostgreSQL database dump complete
""",
            encoding="utf-8"
        )
        res = self.run_verify(["--service", "postgres", "--dir", str(pg_dir), "--verbose"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PostgreSQL dump integrity validation SUCCEEDED", res.stdout)
        self.assertIn("2 table definitions declared", res.stdout)

    def test_empty_postgres_dump(self):
        pg_dir = self.sandbox / "postgres"
        pg_dir.mkdir(parents=True)
        dump_file = pg_dir / "dump.sql"
        dump_file.write_text("", encoding="utf-8")

        res = self.run_verify(["--service", "postgres", "--dir", str(pg_dir)])
        self.assertEqual(res.returncode, 8)
        self.assertIn("empty (0 bytes)", res.stderr)

    def test_postgres_dump_without_tables(self):
        pg_dir = self.sandbox / "postgres"
        pg_dir.mkdir(parents=True)
        dump_file = pg_dir / "dump.sql"
        dump_file.write_text(
            """-- PostgreSQL database dump
-- Empty database without table declarations
SET client_encoding = 'UTF8';
""",
            encoding="utf-8"
        )
        res = self.run_verify(["--service", "postgres", "--dir", str(pg_dir)])
        self.assertEqual(res.returncode, 8)
        self.assertIn("table count assertion FAILED", res.stderr)


class TestDirectFileVerification(BaseDRIntegrityTestCase):
    def test_corrupt_sqlite_file(self):
        db_path = self.sandbox / "corrupt.sqlite"
        self.create_sqlite_db(
            db_path,
            "CREATE TABLE sample (id INT PRIMARY KEY); INSERT INTO sample VALUES (1);"
        )
        # Corrupt SQLite database root page (bytes 100-600)
        with open(db_path, "r+b") as fp:
            fp.seek(100)
            fp.write(b"\x00" * 500)

        res = self.run_verify(["--file", str(db_path)])
        self.assertEqual(res.returncode, 2)
        self.assertIn("malformed", res.stderr.lower())

    def test_valid_single_sqlite_file(self):
        db_path = self.sandbox / "healthy.sqlite"
        self.create_sqlite_db(
            db_path,
            "CREATE TABLE sample (id INT PRIMARY KEY); INSERT INTO sample VALUES (1);"
        )
        res = self.run_verify(["--file", str(db_path)])
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_single_postgres_dump_file(self):
        dump_path = self.sandbox / "standalone.sql"
        dump_path.write_text(
            "CREATE TABLE tbl (id int);\nINSERT INTO tbl VALUES (1);\n",
            encoding="utf-8"
        )
        res = self.run_verify(["--file", str(dump_path)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PostgreSQL dump integrity validation SUCCEEDED", res.stdout)

    def test_single_rsa_key_file(self):
        key_path = self.sandbox / "rsa_key.pem"
        self.generate_rsa_key(key_path, mode=0o600)
        res = self.run_verify(["--file", str(key_path)])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("RSA private key verified successfully", res.stdout)


class TestMultiServiceAutoDetection(BaseDRIntegrityTestCase):
    def test_unrecognized_empty_directory(self):
        empty_dir = self.sandbox / "empty_dir"
        empty_dir.mkdir()
        res = self.run_verify(["--dir", str(empty_dir)])
        self.assertEqual(res.returncode, 1)
        self.assertIn("No recognized service backup artifacts found", res.stderr)

    def test_multi_service_auto_detection_success(self):
        combo_dir = self.sandbox / "combo"
        (combo_dir / "server-files").mkdir(parents=True)
        (combo_dir / "user-files").mkdir(parents=True)
        (combo_dir / "attachments").mkdir(parents=True)
        (combo_dir / "sends").mkdir(parents=True)
        (combo_dir / ".storage").mkdir(parents=True)

        # Actual Budget
        self.create_sqlite_db(
            combo_dir / "server-files" / "account.sqlite",
            "CREATE TABLE users (id TEXT PRIMARY KEY); INSERT INTO users VALUES ('u1');"
        )
        (combo_dir / "user-files" / "test.blob").write_bytes(b"blob-content")

        # Vaultwarden
        self.create_sqlite_db(
            combo_dir / "db.sqlite3",
            "CREATE TABLE users (id TEXT PRIMARY KEY); CREATE TABLE ciphers (id TEXT); INSERT INTO users VALUES ('u1');"
        )
        self.generate_rsa_key(combo_dir / "rsa_key.pem", mode=0o600)

        # Home Assistant
        self.create_sqlite_db(
            combo_dir / "home-assistant_v2.db",
            "CREATE TABLE states (id INT PRIMARY KEY);"
        )
        (combo_dir / ".storage" / "core.config").write_text('{"version": 1}', encoding="utf-8")

        # Postgres
        (combo_dir / "dump.sql").write_text(
            "-- PostgreSQL database dump\nCREATE TABLE accounts (id int);\n",
            encoding="utf-8"
        )

        res = self.run_verify(["--dir", str(combo_dir), "--verbose"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("All 4 detected service backup(s) passed deep integrity verification", res.stdout)


if __name__ == "__main__":
    unittest.main()
