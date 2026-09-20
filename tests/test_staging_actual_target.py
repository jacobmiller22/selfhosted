#!/usr/bin/env python3
"""
Unit and integration tests for Actual Budget Staging Target Automation Verification
(tools/staging/test-actual-staging.sh).

Verifies:
1. CLI option parsing, argument validation, timeout checks, and help text.
2. Dry-run execution flow with step-by-step validation of all 7 operational phases.
3. Production bit-for-bit unchanged assertion logic (cryptographic SHA256 checksum match).
4. Detection of production database tampering or file deletion (zero-side-effect enforcement).
5. Staging database transaction & category query/modification verification.
6. Teardown trap handler execution and --keep retention flag.
7. Remote host verification protocol (RHVP) and exit code semantics.
8. Compose and configuration documentation integrity for staging redirection.
"""

import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "staging" / "test-actual-staging.sh"


class TestActualStagingCLI(unittest.TestCase):
    """Test CLI argument parsing, flags, and input validation."""

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
            self.assertIn("test-actual-staging.sh", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--keep", res.stdout)
            self.assertIn("--skip-hydrate", res.stdout)
            self.assertIn("--timeout", res.stdout)
            self.assertIn("--host", res.stdout)
            self.assertIn("--url", res.stdout)
            self.assertIn("--prod-data-dir", res.stdout)
            self.assertIn("--stage-data-dir", res.stdout)
            self.assertIn("Zero-side-effect assertion", res.stdout)

    def test_unknown_cli_option_fails(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--non-existent-option"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unknown option: --non-existent-option", res.stderr)

    def test_missing_option_value_fails(self):
        for flag in ["--timeout", "--host", "--prod-data-dir", "--stage-data-dir", "--url"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn(f"Missing value for {flag}", res.stderr)

    def test_invalid_timeout_fails(self):
        for invalid in ["0", "-10", "abc"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "--timeout", invalid],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("Timeout must be a positive integer", res.stderr)

    def test_dry_run_standard_execution(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("🚀 [DRY-RUN] Actual Budget Staging Target Automation Verification", res.stdout)
        self.assertIn("Step 1: Pre-flight reachability checks", res.stdout)
        self.assertIn("Step 2: Production snapshot hydration", res.stdout)
        self.assertIn("Step 3: Record SHA256 checksum of production database before test", res.stdout)
        self.assertIn("Step 4: Target Actual staging instance with batch test queries", res.stdout)
        self.assertIn("Step 5: Verify transactions and categories can be queried and modified in staging", res.stdout)
        self.assertIn("Step 6: Zero-side-effect assertion", res.stdout)
        self.assertIn("Step 7: Teardown staging container", res.stdout)
        self.assertIn("✅ [DRY-RUN] Actual Budget staging target verification plan validated successfully", res.stdout)

    def test_dry_run_custom_options(self):
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--dry-run",
                "--host", "bjorn",
                "--timeout", "45",
                "--keep",
                "--skip-hydrate",
                "--prod-data-dir", "/test/custom/prod",
                "--stage-data-dir", "/test/custom/stage",
                "--url", "http://10.0.0.1:5006",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Target Host:           bjorn", res.stdout)
        self.assertIn("Target Staging URL:    http://10.0.0.1:5006", res.stdout)
        self.assertIn("Timeout:               45s", res.stdout)
        self.assertIn("Keep Container:        true", res.stdout)
        self.assertIn("Production Data Dir:   /test/custom/prod", res.stdout)
        self.assertIn("Staging Data Dir:      /test/custom/stage", res.stdout)
        self.assertIn("Production snapshot hydration skipped (--skip-hydrate)", res.stdout)
        self.assertIn("would verify SSH reachability", res.stdout)


class TestActualStagingBitForBitProtection(unittest.TestCase):
    """Test the zero-side-effect bit-for-bit immutability assertion."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="actual_staging_test_")
        self.prod_dir = Path(self.test_dir) / "prod"
        self.stage_dir = Path(self.test_dir) / "stage"
        self.bin_dir = Path(self.test_dir) / "bin"

        self.prod_dir.mkdir(parents=True)
        self.stage_dir.mkdir(parents=True)
        self.bin_dir.mkdir(parents=True)

        # Mock curl that returns HTTP 200 for health probe
        mock_curl = self.bin_dir / "curl"
        mock_curl.write_text(
            "#!/usr/bin/env bash\n"
            "echo '200'\n"
            "exit 0\n"
        )
        mock_curl.chmod(mock_curl.stat().st_mode | stat.S_IEXEC)

        # Mock docker that returns success
        mock_docker = self.bin_dir / "docker"
        mock_docker.write_text(
            "#!/usr/bin/env bash\n"
            "exit 0\n"
        )
        mock_docker.chmod(mock_docker.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _init_sqlite_db(self, path: Path, tables: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        for table_name, (schema, rows) in tables.items():
            cur.execute(f"CREATE TABLE {table_name} ({schema});")
            for row in rows:
                placeholders = ",".join(["?"] * len(row))
                cur.execute(f"INSERT INTO {table_name} VALUES ({placeholders});", row)
        conn.commit()
        conn.close()

    def test_zero_side_effect_passed_when_prod_unchanged(self):
        # 1. Initialize production databases
        account_db = self.prod_dir / "server-files" / "account.sqlite"
        self._init_sqlite_db(account_db, {
            "users": ("id TEXT PRIMARY KEY, email TEXT", [("u1", "user@example.com")])
        })

        budget_db = self.prod_dir / "user-files" / "budget-001.sqlite"
        self._init_sqlite_db(budget_db, {
            "categories": ("id TEXT PRIMARY KEY, name TEXT", [("c1", "Groceries"), ("c2", "Rent")]),
            "transactions": ("id TEXT PRIMARY KEY, is_parent INT, is_child INT", [("tx1", 0, 0)])
        })

        # 2. Initialize staging database as copy
        stage_budget_db = self.stage_dir / "user-files" / "budget-001.sqlite"
        stage_budget_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(budget_db, stage_budget_db)

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"

        # 3. Run test-actual-staging.sh
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
                "--timeout", "5",
                "--url", "http://localhost:5006",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

        self.assertEqual(res.returncode, 0, f"Script failed: {res.stderr}\nOutput: {res.stdout}")
        self.assertIn("Zero-Side-Effect Assertion PASSED", res.stdout)
        self.assertIn("Production database files remain 100% bit-for-bit identical", res.stdout)
        self.assertIn("Staging category modification verified successfully", res.stdout)
        self.assertIn("Staging transaction modification verified successfully", res.stdout)

        # Confirm staging database was modified
        stage_conn = sqlite3.connect(str(stage_budget_db))
        stage_cats = stage_conn.cursor().execute("SELECT count(*) FROM categories;").fetchone()[0]
        self.assertEqual(stage_cats, 3, "Staging should have 3 categories after test insertion")
        stage_conn.close()

        # Confirm production database was NOT modified
        prod_conn = sqlite3.connect(str(budget_db))
        prod_cats = prod_conn.cursor().execute("SELECT count(*) FROM categories;").fetchone()[0]
        self.assertEqual(prod_cats, 2, "Production MUST remain with 2 categories (bit-for-bit unchanged)")
        prod_conn.close()

    def test_zero_side_effect_fails_when_prod_tampered(self):
        # 1. Initialize production databases
        account_db = self.prod_dir / "server-files" / "account.sqlite"
        self._init_sqlite_db(account_db, {
            "users": ("id TEXT PRIMARY KEY, email TEXT", [("u1", "user@example.com")])
        })

        budget_db = self.prod_dir / "user-files" / "budget-001.sqlite"
        self._init_sqlite_db(budget_db, {
            "categories": ("id TEXT PRIMARY KEY, name TEXT", [("c1", "Groceries")]),
            "transactions": ("id TEXT PRIMARY KEY, is_parent INT, is_child INT", [("tx1", 0, 0)])
        })

        stage_budget_db = self.stage_dir / "user-files" / "budget-001.sqlite"
        stage_budget_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(budget_db, stage_budget_db)

        # Create a mock sqlite3 wrapper that modifies prod_db during Step 5
        tamper_marker = Path(self.test_dir) / "tampered"
        mock_sqlite3 = self.bin_dir / "sqlite3"
        mock_sqlite3.write_text(
            f"#!/usr/bin/env bash\n"
            f"# If not already tampered, mutate production db\n"
            f"if [ ! -f '{tamper_marker}' ]; then\n"
            f"  touch '{tamper_marker}'\n"
            f"  /usr/bin/sqlite3 '{budget_db}' \"INSERT INTO categories VALUES ('rogue', 'Rogue Mutation');\"\n"
            f"fi\n"
            f"exec /usr/bin/sqlite3 \"$@\"\n"
        )
        mock_sqlite3.chmod(mock_sqlite3.stat().st_mode | stat.S_IEXEC)

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
                "--timeout", "5",
                "--url", "http://localhost:5006",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

        self.assertEqual(res.returncode, 6, f"Expected exit code 6 for side-effect failure, got {res.returncode}")
        self.assertIn("CRITICAL FAILURE: Production database modified during staging test", res.stderr)
        self.assertIn("FATAL ERROR: Zero-side-effect assertion FAILED", res.stderr)

    def test_zero_side_effect_fails_when_prod_file_deleted(self):
        account_db = self.prod_dir / "server-files" / "account.sqlite"
        self._init_sqlite_db(account_db, {
            "users": ("id TEXT PRIMARY KEY, email TEXT", [("u1", "user@example.com")])
        })

        budget_db = self.prod_dir / "user-files" / "budget-001.sqlite"
        self._init_sqlite_db(budget_db, {
            "categories": ("id TEXT PRIMARY KEY, name TEXT", [("c1", "Groceries")]),
            "transactions": ("id TEXT PRIMARY KEY, is_parent INT, is_child INT", [("tx1", 0, 0)])
        })

        stage_budget_db = self.stage_dir / "user-files" / "budget-001.sqlite"
        stage_budget_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(budget_db, stage_budget_db)

        # Mock sqlite3 wrapper that deletes budget_db
        delete_marker = Path(self.test_dir) / "deleted"
        mock_sqlite3 = self.bin_dir / "sqlite3"
        mock_sqlite3.write_text(
            f"#!/usr/bin/env bash\n"
            f"if [ ! -f '{delete_marker}' ]; then\n"
            f"  touch '{delete_marker}'\n"
            f"  rm -f '{budget_db}'\n"
            f"fi\n"
            f"exec /usr/bin/sqlite3 \"$@\"\n"
        )
        mock_sqlite3.chmod(mock_sqlite3.stat().st_mode | stat.S_IEXEC)

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
                "--timeout", "5",
                "--url", "http://localhost:5006",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

        self.assertEqual(res.returncode, 6)
        self.assertIn("CRITICAL FAILURE: Production file missing after staging test", res.stderr)


class TestActualStagingDatabaseVerification(unittest.TestCase):
    """Test staging database integrity checks and query/modification logic."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="actual_stage_query_")
        self.prod_dir = Path(self.test_dir) / "prod"
        self.stage_dir = Path(self.test_dir) / "stage"
        self.bin_dir = Path(self.test_dir) / "bin"

        self.prod_dir.mkdir(parents=True)
        self.stage_dir.mkdir(parents=True)
        self.bin_dir.mkdir(parents=True)

        mock_curl = self.bin_dir / "curl"
        mock_curl.write_text("#!/usr/bin/env bash\necho '200'\nexit 0\n")
        mock_curl.chmod(mock_curl.stat().st_mode | stat.S_IEXEC)

        mock_docker = self.bin_dir / "docker"
        mock_docker.write_text("#!/usr/bin/env bash\nexit 0\n")
        mock_docker.chmod(mock_docker.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_staging_corrupted_database_fails_integrity(self):
        # Corrupt staging SQLite file
        corrupt_db = self.stage_dir / "user-files" / "corrupt.sqlite"
        corrupt_db.parent.mkdir(parents=True, exist_ok=True)
        corrupt_db.write_bytes(b"SQLite format 3\x00corrupted garbage data header bytes" * 10)

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
                "--timeout", "5",
                "--url", "http://localhost:5006",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

        self.assertEqual(res.returncode, 5)
        self.assertIn("Staging SQLite integrity check failed", res.stderr)

    def test_health_probe_timeout_fails(self):
        # Mock curl that always fails or returns 502
        failing_curl = self.bin_dir / "curl"
        failing_curl.write_text("#!/usr/bin/env bash\necho '502'\nexit 1\n")
        failing_curl.chmod(failing_curl.stat().st_mode | stat.S_IEXEC)

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--prod-data-dir", str(self.prod_dir),
                "--stage-data-dir", str(self.stage_dir),
                "--timeout", "2",
                "--url", "http://localhost:5006",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

        self.assertEqual(res.returncode, 4)
        self.assertIn("Staging health probe timed out after 2s", res.stderr)


class TestActualStagingTrapAndRetention(unittest.TestCase):
    """Test teardown trap handling and retention with --keep."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="actual_stage_trap_")
        self.bin_dir = Path(self.test_dir) / "bin"
        self.bin_dir.mkdir(parents=True)

        mock_curl = self.bin_dir / "curl"
        mock_curl.write_text("#!/usr/bin/env bash\necho '200'\nexit 0\n")
        mock_curl.chmod(mock_curl.stat().st_mode | stat.S_IEXEC)

        self.docker_log = Path(self.test_dir) / "docker_calls.log"
        mock_docker = self.bin_dir / "docker"
        mock_docker.write_text(
            f"#!/usr/bin/env bash\n"
            f"echo \"$@\" >> '{self.docker_log}'\n"
            f"exit 0\n"
        )
        mock_docker.chmod(mock_docker.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_teardown_executes_docker_stop_and_rm(self):
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--prod-data-dir", str(self.test_dir),
                "--stage-data-dir", str(self.test_dir),
                "--timeout", "3",
                "--url", "http://localhost:5006",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

        self.assertEqual(res.returncode, 0)
        self.assertIn("Step 7: Teardown: Stopping and removing staging container", res.stdout)
        self.assertIn("Teardown completed successfully", res.stdout)

        docker_calls = self.docker_log.read_text()
        self.assertIn("stop actual-server-staging", docker_calls)
        self.assertIn("rm -f actual-server-staging", docker_calls)

    def test_keep_flag_preserves_container(self):
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--skip-hydrate",
                "--keep",
                "--prod-data-dir", str(self.test_dir),
                "--stage-data-dir", str(self.test_dir),
                "--timeout", "3",
                "--url", "http://localhost:5006",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )

        self.assertEqual(res.returncode, 0)
        self.assertIn("Notice: Staging container 'actual-server-staging' kept running (--keep flag specified)", res.stdout)

        docker_calls = self.docker_log.read_text()
        self.assertNotIn("stop actual-server-staging", docker_calls)


class TestActualStagingRemoteSSH(unittest.TestCase):
    """Test remote host verification and command dispatch patterns."""

    def test_unreachable_remote_host_fails_rhvp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir) / "bin"
            bin_dir.mkdir()

            # Mock ssh that fails reachability check
            mock_ssh = bin_dir / "ssh"
            mock_ssh.write_text(
                "#!/usr/bin/env bash\n"
                "exit 255\n"
            )
            mock_ssh.chmod(mock_ssh.stat().st_mode | stat.S_IEXEC)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

            res = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--host", "unreachable-test-host",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(REPO_ROOT),
            )

            self.assertEqual(res.returncode, 2)
            self.assertIn("Remote host 'unreachable-test-host' is unreachable via SSH", res.stderr)


class TestActualStagingDocsAndConfiguration(unittest.TestCase):
    """Test compose configuration, environment settings, and architecture documentation."""

    def test_compose_networks_and_aliases(self):
        compose_path = REPO_ROOT / "actual" / "compose.yml"
        with open(compose_path, "r", encoding="utf-8") as f:
            compose_data = yaml.safe_load(f)

        services = compose_data.get("services", {})
        staging_svc = services.get("actual-server-staging", {})
        self.assertIn("staging", staging_svc.get("profiles", []))

        # Check networks for actual-server-staging
        stage_networks = staging_svc.get("networks", {})
        if isinstance(stage_networks, dict):
            self.assertIn("staging-net", stage_networks)
            aliases = stage_networks["staging-net"].get("aliases", [])
            self.assertIn("actual-staging", aliases)
        elif isinstance(stage_networks, list):
            self.assertIn("staging-net", stage_networks)

        # Check actual-auto-categorizer has access to staging-net
        categorizer_svc = services.get("actual-auto-categorizer", {})
        cat_networks = categorizer_svc.get("networks", [])
        self.assertIn("staging-net", cat_networks)

    def test_staging_architecture_documentation(self):
        doc_path = REPO_ROOT / "docs" / "STAGING_ARCHITECTURE.md"
        self.assertTrue(doc_path.exists())
        content = doc_path.read_text(encoding="utf-8")

        self.assertIn("test-actual-staging.sh", content)
        self.assertIn("Actual Budget Client & Sync Segregation Safeguards", content)
        self.assertIn("Zero-Side-Effect Assertion", content)
        self.assertIn("SHA256", content)
        self.assertIn("ACTUAL_SERVER_URL=http://localhost:5006", content)
        self.assertIn("actual-staging:5006", content)

    def test_agents_documentation(self):
        agents_path = REPO_ROOT / "actual" / "AGENTS.md"
        self.assertTrue(agents_path.exists())
        content = agents_path.read_text(encoding="utf-8")

        self.assertIn("test-actual-staging.sh", content)
        self.assertIn("ACTUAL_SERVER_URL=http://localhost:5006", content)
        self.assertIn("actual-staging:5006", content)

    def test_transaction_importer_env_example(self):
        env_example_path = REPO_ROOT / "actual" / "tools" / "transaction-importer" / ".env.example"
        self.assertTrue(env_example_path.exists())
        content = env_example_path.read_text(encoding="utf-8")

        self.assertIn("http://localhost:5006", content)
        self.assertIn("http://actual-staging:5006", content)


if __name__ == "__main__":
    unittest.main()
