#!/usr/bin/env python3
"""
Unit and integration tests for Vaultwarden Staging Upgrade Sandbox & Safe Schema
Migration Runbook (tools/staging/verify-vaultwarden-upgrade.sh).

Verifies:
1. CLI argument parsing, flags, timeout validation, error handling, and help text.
2. Dry-run execution flow with step-by-step validation of all 7 operational phases.
3. Log monitoring logic: detecting SQLite schema migration, database locks, and Rust panics.
4. Health probing: verification of /alive and Web Vault assets loading, with timeout traps.
5. SQLite database integrity checks on staging db.sqlite3 (PRAGMA integrity_check).
6. Client segregation assertion: SIGNUPS_ALLOWED=false and isolated localhost domain.
7. Teardown trap handler: guaranteed cleanup on exit/error unless --keep is passed.
"""

import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "staging" / "verify-vaultwarden-upgrade.sh"


class TestVaultwardenUpgradeCLI(unittest.TestCase):
    """Test CLI flags, argument parsing, and input validation."""

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
            self.assertIn("<new-image-tag>", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--skip-hydrate", res.stdout)
            self.assertIn("--timeout", res.stdout)
            self.assertIn("--host", res.stdout)
            self.assertIn("--keep", res.stdout)

    def test_missing_candidate_tag_fails(self):
        res = subprocess.run(
            [str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Candidate image tag is required", res.stderr)

    def test_unknown_cli_option_fails(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--invalid-option", "1.35.5"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unknown option: --invalid-option", res.stderr)

    def test_missing_option_value_fails(self):
        for flag in ["--timeout", "--host", "--stage-data-dir", "--prod-data-dir"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn(f"Missing value for {flag}", res.stderr)

    def test_invalid_timeout_fails(self):
        for invalid in ["-10", "0", "abc"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "--timeout", invalid, "1.35.5"],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("Timeout must be a positive integer", res.stderr)

    def test_unexpected_positional_arguments_fails(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "1.35.5", "unexpected-second-tag"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unexpected positional argument", res.stderr)


class TestDryRunExecutionFlow(unittest.TestCase):
    """Test deterministic dry-run execution flow across all verification steps."""

    def test_dry_run_basic_flow(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run", "1.35.5"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Dry-run failed: {res.stderr}\n{res.stdout}")
        self.assertIn("[DRY-RUN]", res.stdout)
        self.assertIn("IMAGE_TAG=1.35.5", res.stdout)

        # Assert all 7 phases appear in dry-run output
        self.assertIn("Step 1: Pre-flight snapshot hydration", res.stdout)
        self.assertIn("hydrate.sh vaultwarden --dry-run", res.stdout)
        self.assertIn("Step 2: Spin up staging container 'vaultwarden-staging'", res.stdout)
        self.assertIn("--profile staging up -d vaultwarden-staging", res.stdout)
        self.assertIn("Step 3: Monitor container logs for schema migration", res.stdout)
        self.assertIn("Step 4: Health probe endpoints on port 7278", res.stdout)
        self.assertIn("http://localhost:7278/alive", res.stdout)
        self.assertIn("http://localhost:7278/", res.stdout)
        self.assertIn("Step 5: SQLite integrity check", res.stdout)
        self.assertIn("PRAGMA integrity_check;", res.stdout)
        self.assertIn("Step 6: Client segregation assertion", res.stdout)
        self.assertIn("SIGNUPS_ALLOWED=false", res.stdout)
        self.assertIn("DOMAIN=http://localhost:7278", res.stdout)
        self.assertIn("Step 7: Teardown: Stopping and removing staging container", res.stdout)
        self.assertIn("--profile staging down", res.stdout)

    def test_dry_run_skip_hydrate(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run", "--skip-hydrate", "1.35.5"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Step 1: Pre-flight hydration skipped (--skip-hydrate)", res.stdout)
        self.assertNotIn("hydrate.sh vaultwarden", res.stdout)

    def test_dry_run_custom_timeout_and_host(self):
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--dry-run",
                "--timeout", "60",
                "--host", "bjorn",
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Target Host:        bjorn", res.stdout)
        self.assertIn("Timeout:            60s", res.stdout)

    def test_dry_run_keep_container(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run", "--keep", "1.35.5"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Keep Container:     true", res.stdout)
        self.assertIn("Staging container kept running (--keep flag specified)", res.stdout)
        self.assertNotIn("Step 7: Teardown", res.stdout)

    def test_dry_run_tag_normalization(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run", "vaultwarden/server:1.36.0"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Candidate Image Tag: vaultwarden/server:1.36.0 (IMAGE_TAG=1.36.0)", res.stdout)
        self.assertIn("IMAGE_TAG=1.36.0", res.stdout)


class TestLogInspectionAndFailureDetection(unittest.TestCase):
    """Test detection of schema migrations, Rust panics, and SQLite lock errors."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_vw_logs_")
        self.stage_dir = Path(self.test_dir) / "stage"
        self.stage_dir.mkdir()

        # Seed valid sqlite DB so step 5 passes when not aborted early
        self.db_path = self.stage_dir / "db.sqlite3"
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("CREATE TABLE test (id TEXT PRIMARY KEY);")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_docker(self, log_output: str, inspect_output: str = 'SIGNUPS_ALLOWED=false\nDOMAIN=http://localhost:7278'):
        log_file = Path(self.test_dir) / "container.log"
        log_file.write_text(log_output, encoding="utf-8")

        mock_docker = Path(self.test_dir) / "mock_docker.sh"
        mock_docker.write_text(
            f"""#!/usr/bin/env bash
if [[ "$1" == "logs" ]]; then
  cat "{log_file}"
  exit 0
elif [[ "$1" == "inspect" ]]; then
  cat <<'ENVEOF'
{inspect_output}
ENVEOF
  exit 0
elif [[ "$1" == "compose" ]]; then
  exit 0
fi
exit 0
""",
            encoding="utf-8",
        )
        mock_docker.chmod(0o755)
        return mock_docker

    def _create_mock_curl(self, status: str = "200"):
        mock_curl = Path(self.test_dir) / "mock_curl.sh"
        mock_curl.write_text(
            f"""#!/usr/bin/env bash
printf "%s" "{status}"
exit 0
""",
            encoding="utf-8",
        )
        mock_curl.chmod(0o755)
        return mock_curl

    def test_rust_panic_detected_in_logs(self):
        panic_logs = """[2026-09-19 12:00:00.000][vaultwarden::api::core][INFO] Launching server...
thread 'main' panicked at 'assertion failed: schema version match', src/db/models.rs:142:9
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
"""
        mock_docker = self._create_mock_docker(panic_logs)
        mock_curl = self._create_mock_curl("200")

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(mock_docker)
        env["CURL_CMD"] = str(mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0, "Script must fail on Rust panic in logs")
        self.assertIn("Rust panic detected in container logs", res.stderr)

    def test_sqlite_lock_error_detected_in_logs(self):
        lock_logs = """[2026-09-19 12:00:00.000][vaultwarden::db][ERROR] Diesel error: database is locked
SqliteFailure(Error { code: DatabaseLocked, extended_code: 5 }, Some("database is locked"))
"""
        mock_docker = self._create_mock_docker(lock_logs)
        mock_curl = self._create_mock_curl("200")

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(mock_docker)
        env["CURL_CMD"] = str(mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0, "Script must fail on SQLite database lock")
        self.assertIn("SQLite database lock detected in container logs", res.stderr)

    def test_schema_migration_detected_and_reported(self):
        migration_logs = """[2026-09-19 12:00:00.000][vaultwarden::db][INFO] Executing migration 2026-09-01_add_passkey_table
[2026-09-19 12:00:00.100][vaultwarden::db][INFO] Applied migration 2026-09-01_add_passkey_table
[2026-09-19 12:00:00.200][rocket::launch][INFO] Rocket has launched from http://0.0.0.0:80
"""
        mock_docker = self._create_mock_docker(migration_logs)
        mock_curl = self._create_mock_curl("200")

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(mock_docker)
        env["CURL_CMD"] = str(mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Run failed: {res.stderr}\n{res.stdout}")
        self.assertIn("SQLite schema migration output detected and completed successfully", res.stdout)


class TestHealthProbeAndTimeout(unittest.TestCase):
    """Test health probe checks and timeout escalation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_vw_health_")
        self.stage_dir = Path(self.test_dir) / "stage"
        self.stage_dir.mkdir()

        # Seed valid sqlite DB
        self.db_path = self.stage_dir / "db.sqlite3"
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("CREATE TABLE test (id INT);")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_health_probe_timeout_fails(self):
        # Mock docker with healthy logs but curl returns 500 (unhealthy)
        mock_docker = Path(self.test_dir) / "mock_docker.sh"
        mock_docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        mock_docker.chmod(0o755)

        mock_curl = Path(self.test_dir) / "mock_curl.sh"
        mock_curl.write_text("#!/usr/bin/env bash\nprintf '502'\nexit 0\n", encoding="utf-8")
        mock_curl.chmod(0o755)

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(mock_docker)
        env["CURL_CMD"] = str(mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "1",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Health probe timed out after 1s", res.stderr)


class TestSQLiteIntegrityCheck(unittest.TestCase):
    """Test PRAGMA integrity_check validation on hydrated database."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_vw_integrity_")
        self.stage_dir = Path(self.test_dir) / "stage"
        self.stage_dir.mkdir()

        self.mock_docker = Path(self.test_dir) / "mock_docker.sh"
        self.mock_docker.write_text(
            """#!/usr/bin/env bash
if [[ "$1" == "inspect" ]]; then
  echo "SIGNUPS_ALLOWED=false"
  echo "DOMAIN=http://localhost:7278"
fi
exit 0
""",
            encoding="utf-8",
        )
        self.mock_docker.chmod(0o755)

        self.mock_curl = Path(self.test_dir) / "mock_curl.sh"
        self.mock_curl.write_text("#!/usr/bin/env bash\nprintf '200'\nexit 0\n", encoding="utf-8")
        self.mock_curl.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_integrity_check_succeeds_on_valid_db(self):
        db_path = self.stage_dir / "db.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE ciphers (uuid TEXT PRIMARY KEY, cipher TEXT);")
        conn.execute("INSERT INTO ciphers VALUES ('c1', 'data1');")
        conn.commit()
        conn.close()

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(self.mock_docker)
        env["CURL_CMD"] = str(self.mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Integrity check failed: {res.stderr}\n{res.stdout}")
        self.assertIn("SQLite integrity check passed: db.sqlite3 verified consistent (ok)", res.stdout)

    def test_integrity_check_fails_on_corrupted_db(self):
        db_path = self.stage_dir / "db.sqlite3"
        # Write corrupted non-sqlite bytes
        db_path.write_bytes(b"CORRUPTED_SQLITE_BINARY_STREAM_123456789")

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(self.mock_docker)
        env["CURL_CMD"] = str(self.mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("SQLite integrity check failed on staging database", res.stderr)


class TestClientSegregationAssertions(unittest.TestCase):
    """Test client segregation assertions against configuration drift."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_vw_segregation_")
        self.stage_dir = Path(self.test_dir) / "stage"
        self.stage_dir.mkdir()

        # Seed valid db
        db_path = self.stage_dir / "db.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE ciphers (id TEXT);")
        conn.commit()
        conn.close()

        self.mock_curl = Path(self.test_dir) / "mock_curl.sh"
        self.mock_curl.write_text("#!/usr/bin/env bash\nprintf '200'\nexit 0\n", encoding="utf-8")
        self.mock_curl.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_segregation_fails_when_signups_allowed_true(self):
        mock_docker = Path(self.test_dir) / "mock_docker.sh"
        mock_docker.write_text(
            """#!/usr/bin/env bash
if [[ "$1" == "inspect" ]]; then
  echo "SIGNUPS_ALLOWED=true"
  echo "DOMAIN=http://localhost:7278"
fi
exit 0
""",
            encoding="utf-8",
        )
        mock_docker.chmod(0o755)

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(mock_docker)
        env["CURL_CMD"] = str(self.mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("SIGNUPS_ALLOWED is 'true' (must be 'false')", res.stderr)

    def test_segregation_fails_when_production_domain_configured(self):
        mock_docker = Path(self.test_dir) / "mock_docker.sh"
        mock_docker.write_text(
            """#!/usr/bin/env bash
if [[ "$1" == "inspect" ]]; then
  echo "SIGNUPS_ALLOWED=false"
  echo "DOMAIN=https://vw.cloud.jacobmiller22.com"
fi
exit 0
""",
            encoding="utf-8",
        )
        mock_docker.chmod(0o755)

        env = os.environ.copy()
        env["DOCKER_CMD"] = str(mock_docker)
        env["CURL_CMD"] = str(self.mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("DOMAIN is 'https://vw.cloud.jacobmiller22.com'", res.stderr)


class TestTeardownAndTrapHandler(unittest.TestCase):
    """Test teardown trap handler and cleanup guarantees."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_vw_teardown_")
        self.stage_dir = Path(self.test_dir) / "stage"
        self.stage_dir.mkdir()

        # Valid db
        db_path = self.stage_dir / "db.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE ciphers (id TEXT);")
        conn.commit()
        conn.close()

        self.docker_log = Path(self.test_dir) / "docker_invocations.log"
        self.mock_docker = Path(self.test_dir) / "mock_docker.sh"
        self.mock_docker.write_text(
            f"""#!/usr/bin/env bash
echo "$@" >> "{self.docker_log}"
if [[ "$1" == "inspect" ]]; then
  echo "SIGNUPS_ALLOWED=false"
  echo "DOMAIN=http://localhost:7278"
fi
exit 0
""",
            encoding="utf-8",
        )
        self.mock_docker.chmod(0o755)

        self.mock_curl = Path(self.test_dir) / "mock_curl.sh"
        self.mock_curl.write_text("#!/usr/bin/env bash\nprintf '200'\nexit 0\n", encoding="utf-8")
        self.mock_curl.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_teardown_runs_by_default_on_success(self):
        env = os.environ.copy()
        env["DOCKER_CMD"] = str(self.mock_docker)
        env["CURL_CMD"] = str(self.mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Failed: {res.stderr}\n{res.stdout}")
        self.assertIn("Teardown completed successfully", res.stdout)

        log_content = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("compose -f", log_content)
        self.assertIn("--profile staging down", log_content)

    def test_teardown_skipped_when_keep_flag_passed(self):
        env = os.environ.copy()
        env["DOCKER_CMD"] = str(self.mock_docker)
        env["CURL_CMD"] = str(self.mock_curl)

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--keep",
                "--timeout", "5",
                "--stage-data-dir", str(self.stage_dir),
                "1.35.5",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Staging container kept running (--keep flag specified)", res.stdout)

        log_content = self.docker_log.read_text(encoding="utf-8")
        self.assertNotIn("--profile staging down", log_content)


if __name__ == "__main__":
    unittest.main()
