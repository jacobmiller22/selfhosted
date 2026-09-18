#!/usr/bin/env python3
"""
Unit and integration tests for Ephemeral Staging Snapshot Hydration Engine
(tools/staging/hydrate.sh).

Verifies:
1. CLI help flags, options parsing, argument validation, and blast-radius safeguards.
2. Actual Budget hydration workflow: atomic online .backup of account.sqlite and
   user-files/*.sqlite, sync blob copies, ownership enforcement hook, and PRAGMA integrity.
3. Vaultwarden hydration workflow: atomic online .backup of db.sqlite3, companion keys
   (rsa_key.pem chmod 600, rsa_key.pub), attachments, sends, and config.json.
4. Corruption detection: PRAGMA integrity_check step fails if source DB is damaged.
5. Lifecycle controls: --reset wipes and re-hydrates, --stop and --start dispatch to Docker.
"""

import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "staging" / "hydrate.sh"


class TestStagingHydrateCLI(unittest.TestCase):
    """Test CLI argument parsing, flags, and safety validations."""

    def test_script_exists_and_is_executable(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"{SCRIPT_PATH} must exist")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")

    def test_cli_help_flags(self):
        for flag in ["-h", "--help"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0, f"Help flag {flag} should exit 0")
            self.assertIn("Usage:", res.stdout)
            self.assertIn("actual", res.stdout)
            self.assertIn("vaultwarden", res.stdout)
            self.assertIn("--start", res.stdout)
            self.assertIn("--stop", res.stdout)
            self.assertIn("--reset", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--prod-data-dir", res.stdout)
            self.assertIn("--stage-data-dir", res.stdout)

    def test_missing_service_argument(self):
        res = subprocess.run(
            [str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Service name is required", res.stderr)

    def test_unsupported_service_argument(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "unsupported-service"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unknown option: unsupported-service", res.stderr)

    def test_unknown_cli_flag(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--bogus-flag"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unknown option: --bogus-flag", res.stderr)

    def test_missing_flag_value(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--prod-data-dir"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Missing value", res.stderr)

    def test_blast_radius_protection_identical_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_dir = Path(temp_dir) / "shared"
            shared_dir.mkdir()
            res = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "actual",
                    "--prod-data-dir", str(shared_dir),
                    "--stage-data-dir", str(shared_dir),
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("BLAST-RADIUS VIOLATION", res.stderr)

    def test_dry_run_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_prod = Path(temp_dir) / "prod"
            mock_stage = Path(temp_dir) / "stage"
            mock_prod.mkdir()

            res = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "actual",
                    "--dry-run",
                    "--prod-data-dir", str(mock_prod),
                    "--stage-data-dir", str(mock_stage),
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("[dry-run]", res.stdout)
            # In dry-run mode, stage directory should not have been created or modified
            self.assertFalse(mock_stage.exists())


class TestActualBudgetHydration(unittest.TestCase):
    """Test Actual Budget snapshotting, companion files, blobs, and ownership."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_actual_hydrate_")
        self.prod_dir = Path(self.test_dir) / "actual-prod"
        self.stage_dir = Path(self.test_dir) / "actual-stage"
        self.prod_dir.mkdir()
        self.stage_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _init_sqlite_db(self, path: Path, table: str, values: list):
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute(f"PRAGMA journal_mode=WAL;")
        cur.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, val TEXT);")
        for k, v in values:
            cur.execute(f"INSERT INTO {table} VALUES (?, ?);", (k, v))
        conn.commit()
        conn.close()

    def test_actual_budget_standard_hydration(self):
        # 1. Create server-files/account.sqlite
        account_db = self.prod_dir / "server-files" / "account.sqlite"
        self._init_sqlite_db(account_db, "users", [("u1", "alice@example.com"), ("u2", "bob@example.com")])
        # Touch mock wal and shm files
        (self.prod_dir / "server-files" / "account.sqlite-wal").touch()
        (self.prod_dir / "server-files" / "account.sqlite-shm").touch()

        # 2. Create user-files/*.sqlite
        budget_db1 = self.prod_dir / "user-files" / "budget-alpha.sqlite"
        self._init_sqlite_db(budget_db1, "transactions", [("tx1", "100.50"), ("tx2", "-25.00")])
        (self.prod_dir / "user-files" / "budget-alpha.sqlite-wal").touch()

        budget_db2 = self.prod_dir / "user-files" / "budget-beta.sqlite3"
        self._init_sqlite_db(budget_db2, "accounts", [("a1", "Savings"), ("a2", "Checking")])

        # 3. Create user-files/*.blob
        blob1 = self.prod_dir / "user-files" / "sync-1.blob"
        blob1.write_bytes(b"\x00\x01\x02\x03\x04MOCK_ACTUAL_BLOB_SYNC_DATA")
        blob2 = self.prod_dir / "user-files" / "sync-2.blob"
        blob2.write_bytes(b"\xaa\xbb\xcc\xddBINARYSYNC")

        # 4. Companion metadata
        migrate_file = self.prod_dir / ".migrate"
        migrate_file.write_text('{"version": 26}', encoding="utf-8")
        config_file = self.prod_dir / "config.json"
        config_file.write_text('{"server": "actual-test"}', encoding="utf-8")

        # 5. Execute hydration
        chown_marker = Path(self.test_dir) / "chown_invoked.txt"
        env = os.environ.copy()
        env["CHOWN_CMD"] = f"touch {chown_marker}"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "actual",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Hydration failed: {res.stderr}\nOutput: {res.stdout}")
        self.assertIn("Staging hydration for 'actual' completed successfully", res.stdout)

        # 6. Verify hydrated files
        hydrated_account = self.stage_dir / "server-files" / "account.sqlite"
        self.assertTrue(hydrated_account.exists(), "server-files/account.sqlite must be in staging")

        # Query hydrated account database
        conn = sqlite3.connect(str(hydrated_account))
        cur = conn.cursor()
        integrity = cur.execute("PRAGMA integrity_check;").fetchone()[0]
        self.assertEqual(integrity, "ok")
        rows = cur.execute("SELECT id, val FROM users ORDER BY id;").fetchall()
        self.assertEqual(rows, [("u1", "alice@example.com"), ("u2", "bob@example.com")])
        conn.close()

        # Verify user-files
        hydrated_b1 = self.stage_dir / "user-files" / "budget-alpha.sqlite"
        self.assertTrue(hydrated_b1.exists())
        conn_b1 = sqlite3.connect(str(hydrated_b1))
        self.assertEqual(conn_b1.cursor().execute("PRAGMA integrity_check;").fetchone()[0], "ok")
        self.assertEqual(len(conn_b1.cursor().execute("SELECT * FROM transactions;").fetchall()), 2)
        conn_b1.close()

        hydrated_b2 = self.stage_dir / "user-files" / "budget-beta.sqlite3"
        self.assertTrue(hydrated_b2.exists())
        conn_b2 = sqlite3.connect(str(hydrated_b2))
        self.assertEqual(conn_b2.cursor().execute("PRAGMA integrity_check;").fetchone()[0], "ok")
        conn_b2.close()

        # Verify blobs
        hydrated_blob1 = self.stage_dir / "user-files" / "sync-1.blob"
        self.assertTrue(hydrated_blob1.exists())
        self.assertEqual(hydrated_blob1.read_bytes(), b"\x00\x01\x02\x03\x04MOCK_ACTUAL_BLOB_SYNC_DATA")

        # Verify metadata
        self.assertEqual((self.stage_dir / ".migrate").read_text(encoding="utf-8"), '{"version": 26}')
        self.assertEqual((self.stage_dir / "config.json").read_text(encoding="utf-8"), '{"server": "actual-test"}')

        # Verify chown hook was triggered
        self.assertTrue(chown_marker.exists(), "CHOWN_CMD hook must have been executed")

    def test_actual_budget_root_account_sqlite_fallback(self):
        # account.sqlite directly in prod_dir
        account_db = self.prod_dir / "account.sqlite"
        self._init_sqlite_db(account_db, "config", [("c1", "val1")])

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "actual",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Hydration failed: {res.stderr}")
        self.assertTrue((self.stage_dir / "account.sqlite").exists())


class TestVaultwardenHydration(unittest.TestCase):
    """Test Vaultwarden snapshotting, companion keys, attachments, and sends."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_vw_hydrate_")
        self.prod_dir = Path(self.test_dir) / "vw-prod"
        self.stage_dir = Path(self.test_dir) / "vw-stage"
        self.prod_dir.mkdir()
        self.stage_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _init_sqlite_db(self, path: Path, table: str, values: list):
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute(f"PRAGMA journal_mode=WAL;")
        cur.execute(f"CREATE TABLE {table} (uuid TEXT PRIMARY KEY, cipher TEXT);")
        for k, v in values:
            cur.execute(f"INSERT INTO {table} VALUES (?, ?);", (k, v))
        conn.commit()
        conn.close()

    def test_vaultwarden_standard_hydration(self):
        # 1. db.sqlite3
        db_path = self.prod_dir / "db.sqlite3"
        self._init_sqlite_db(db_path, "ciphers", [("cipher-1", "ENCRYPTED_VAULT_ITEM_DATA")])
        (self.prod_dir / "db.sqlite3-wal").touch()
        (self.prod_dir / "db.sqlite3-shm").touch()

        # 2. rsa keys
        rsa_priv = self.prod_dir / "rsa_key.pem"
        rsa_priv.write_text("-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----\n", encoding="utf-8")
        rsa_pub = self.prod_dir / "rsa_key.pub"
        rsa_pub.write_text("-----BEGIN PUBLIC KEY-----\nMOCK_PUB\n-----END PUBLIC KEY-----\n", encoding="utf-8")

        # 3. attachments and sends
        att_dir = self.prod_dir / "attachments"
        att_dir.mkdir()
        (att_dir / "file1.dat").write_bytes(b"ATTACHMENT_RAW_CONTENT")

        send_dir = self.prod_dir / "sends"
        send_dir.mkdir()
        (send_dir / "send1.json").write_text('{"id": "send-1", "active": true}', encoding="utf-8")

        # 4. config.json
        (self.prod_dir / "config.json").write_text('{"signups_allowed": false}', encoding="utf-8")

        # 5. Run hydration
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "vaultwarden",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Vaultwarden hydration failed: {res.stderr}\nOutput: {res.stdout}")
        self.assertIn("Staging hydration for 'vaultwarden' completed successfully", res.stdout)

        # 6. Verify hydrated db.sqlite3
        hydrated_db = self.stage_dir / "db.sqlite3"
        self.assertTrue(hydrated_db.exists())

        conn = sqlite3.connect(str(hydrated_db))
        cur = conn.cursor()
        self.assertEqual(cur.execute("PRAGMA integrity_check;").fetchone()[0], "ok")
        rows = cur.execute("SELECT uuid, cipher FROM ciphers;").fetchall()
        self.assertEqual(rows, [("cipher-1", "ENCRYPTED_VAULT_ITEM_DATA")])
        conn.close()

        # 7. Verify rsa_key.pem permissions (chmod 600)
        hydrated_rsa = self.stage_dir / "rsa_key.pem"
        self.assertTrue(hydrated_rsa.exists())
        file_mode = stat.S_IMODE(os.stat(hydrated_rsa).st_mode)
        self.assertEqual(file_mode, 0o600, f"rsa_key.pem permissions must be 0600, got {oct(file_mode)}")

        # 8. Verify other companion items
        self.assertTrue((self.stage_dir / "rsa_key.pub").exists())
        self.assertEqual((self.stage_dir / "attachments" / "file1.dat").read_bytes(), b"ATTACHMENT_RAW_CONTENT")
        self.assertEqual((self.stage_dir / "sends" / "send1.json").read_text(encoding="utf-8"), '{"id": "send-1", "active": true}')
        self.assertEqual((self.stage_dir / "config.json").read_text(encoding="utf-8"), '{"signups_allowed": false}')


class TestIntegrityValidationAndFailure(unittest.TestCase):
    """Test that PRAGMA integrity_check runs and fails if source database is corrupted."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_integrity_fail_")
        self.prod_dir = Path(self.test_dir) / "prod"
        self.stage_dir = Path(self.test_dir) / "stage"
        self.prod_dir.mkdir()
        self.stage_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_actual_budget_corrupted_account_db_fails(self):
        # Corrupted account.sqlite (not a valid SQLite database)
        server_files = self.prod_dir / "server-files"
        server_files.mkdir()
        (server_files / "account.sqlite").write_bytes(b"CORRUPTED_GARBAGE_HEADER_1234567890")

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "actual",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0, "Hydration must fail when account.sqlite is corrupted")
        self.assertTrue("ERROR" in res.stderr or "Error" in res.stderr)

    def test_actual_budget_corrupted_user_db_fails(self):
        # Valid account.sqlite, corrupted user-files/budget.sqlite
        server_files = self.prod_dir / "server-files"
        server_files.mkdir()
        conn = sqlite3.connect(str(server_files / "account.sqlite"))
        conn.execute("CREATE TABLE users (id INT);")
        conn.commit()
        conn.close()

        user_files = self.prod_dir / "user-files"
        user_files.mkdir()
        (user_files / "budget.sqlite").write_bytes(b"NOT_A_VALID_SQLITE_FILE_CONTENT")

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "actual",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0, "Hydration must fail when user database is corrupted")

    def test_vaultwarden_corrupted_db_fails(self):
        # Corrupted db.sqlite3
        (self.prod_dir / "db.sqlite3").write_bytes(b"MALFORMED_HEADER_BYTES_FOR_VAULTWARDEN")

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "vaultwarden",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0, "Hydration must fail when db.sqlite3 is corrupted")


class TestLifecycleControlsAndReset(unittest.TestCase):
    """Test --reset, --stop, and --start commands."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_lifecycle_")
        self.prod_dir = Path(self.test_dir) / "prod"
        self.stage_dir = Path(self.test_dir) / "stage"
        self.prod_dir.mkdir()
        self.stage_dir.mkdir()

        # Create mock docker dispatcher script
        self.mock_docker_log = Path(self.test_dir) / "docker_calls.log"
        self.mock_docker_script = Path(self.test_dir) / "mock_docker.sh"
        self.mock_docker_script.write_text(
            f"#!/usr/bin/env bash\necho \"$@\" >> \"{self.mock_docker_log}\"\nexit 0\n",
            encoding="utf-8"
        )
        self.mock_docker_script.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _setup_valid_actual_prod(self):
        server_files = self.prod_dir / "server-files"
        server_files.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(server_files / "account.sqlite"))
        conn.executescript("CREATE TABLE users (id TEXT); INSERT INTO users VALUES ('alice');")
        conn.commit()
        conn.close()

    def test_reset_command_wipes_previous_state_and_rehydrates(self):
        self._setup_valid_actual_prod()

        # Seed staging directory with obsolete test artifacts
        stale_file = self.stage_dir / "stale_data.txt"
        stale_file.write_text("old test data to be wiped", encoding="utf-8")
        stale_sub = self.stage_dir / "old_subdir"
        stale_sub.mkdir()
        (stale_sub / "artifact.bin").write_bytes(b"\xff\xff")

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(self.mock_docker_script)

        # 1. Execute --reset <service>
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--reset", "actual",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Reset failed: {res.stderr}\nOutput: {res.stdout}")
        self.assertIn("Initiating staging reset for 'actual'", res.stdout)
        self.assertIn("Staging directory wiped clean", res.stdout)

        # Stale files must be eradicated
        self.assertFalse(stale_file.exists(), "Stale file must be wiped during reset")
        self.assertFalse(stale_sub.exists(), "Stale subdirectory must be wiped during reset")

        # Fresh hydrated database must be present
        hydrated_account = self.stage_dir / "server-files" / "account.sqlite"
        self.assertTrue(hydrated_account.exists())

        # 2. Verify positional syntax: hydrate.sh actual --reset
        (self.stage_dir / "another_stale.txt").write_text("stale", encoding="utf-8")
        res_pos = subprocess.run(
            [
                str(SCRIPT_PATH),
                "actual",
                "--reset",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_pos.returncode, 0)
        self.assertFalse((self.stage_dir / "another_stale.txt").exists())

    def test_stop_command(self):
        env = os.environ.copy()
        env["DOCKER_CMD"] = str(self.mock_docker_script)

        # Stop actual
        res_actual = subprocess.run(
            [str(SCRIPT_PATH), "--stop", "actual"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_actual.returncode, 0)
        self.assertIn("Stopping staging container 'actual-server-staging'", res_actual.stdout)

        # Stop vaultwarden
        res_vw = subprocess.run(
            [str(SCRIPT_PATH), "vaultwarden", "--stop"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_vw.returncode, 0)
        self.assertIn("Stopping staging container 'vaultwarden-staging'", res_vw.stdout)

        # Verify docker invocations
        log_content = self.mock_docker_log.read_text(encoding="utf-8")
        self.assertIn("compose -f", log_content)
        self.assertIn("--profile staging stop actual-server-staging", log_content)
        self.assertIn("--profile staging stop vaultwarden-staging", log_content)

    def test_start_flag_after_hydration(self):
        self._setup_valid_actual_prod()
        env = os.environ.copy()
        env["DOCKER_CMD"] = str(self.mock_docker_script)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "actual",
                "--start",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Hydration with --start failed: {res.stderr}")
        self.assertIn("Starting staging container 'actual-server-staging'", res.stdout)

        log_content = self.mock_docker_log.read_text(encoding="utf-8")
        self.assertIn("compose -f", log_content)
        self.assertIn("--profile staging up -d actual-server-staging", log_content)


if __name__ == "__main__":
    unittest.main()
