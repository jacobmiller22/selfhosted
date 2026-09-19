#!/usr/bin/env python3
"""
Unit tests validating Disaster Recovery (DR) Ephemeral Staging Smoke Test Runner.
Tests CLI options, argument validation, dry-run simulation, container command construction,
remote host SSH wrapping, HTTP endpoint probing, and guaranteed cleanup trap execution.
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "backup-dr" / "staging-smoke-test.sh"


class TestDRStagingSmokeScriptBasics(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"{SCRIPT_PATH} must exist")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")

    def test_shellcheck_clean(self):
        shellcheck_bin = shutil.which("shellcheck")
        if not shellcheck_bin:
            self.skipTest("shellcheck binary not found on PATH")

        res = subprocess.run(
            [shellcheck_bin, "--severity=warning", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"ShellCheck produced warnings:\n{res.stderr}\n{res.stdout}")

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
            self.assertIn("--service", res.stdout)
            self.assertIn("--data-dir", res.stdout)
            self.assertIn("--timeout", res.stdout)
            self.assertIn("--keep", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--host", res.stdout)
            self.assertIn("actual", res.stdout)
            self.assertIn("vaultwarden", res.stdout)
            self.assertIn("Exit Codes:", res.stdout)
            self.assertIn("0", res.stdout)
            self.assertIn("1", res.stdout)
            self.assertIn("2", res.stdout)
            self.assertIn("3", res.stdout)
            self.assertIn("4", res.stdout)

    def test_staging_architecture_documentation_references_smoke_test(self):
        doc_path = REPO_ROOT / "docs" / "STAGING_ARCHITECTURE.md"
        self.assertTrue(doc_path.exists(), "docs/STAGING_ARCHITECTURE.md must exist")
        content = doc_path.read_text(encoding="utf-8")
        self.assertIn("staging-smoke-test.sh", content)
        self.assertIn("5006", content)
        self.assertIn("7278", content)
        self.assertIn("staging-net", content)
        self.assertIn("--dry-run", content)


class TestDRStagingSmokeCLIValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_dr_smoke_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unknown_option_fails(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--unknown-flag"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unknown option", res.stderr)

    def test_missing_option_arguments(self):
        for flag in ["--service", "-s", "--data-dir", "-d", "--timeout", "-t", "--host"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1, f"Missing value for {flag} should exit 1")
            self.assertIn("Missing value", res.stderr)

    def test_unsupported_service_fails(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "invalid_svc"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unsupported service", res.stderr)

    def test_invalid_timeout_values(self):
        for invalid_val in ["0", "-5", "abc"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "--timeout", invalid_val],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1, f"Timeout '{invalid_val}' should exit 1")
            self.assertIn("Timeout must be a positive integer", res.stderr)

        # Empty timeout string triggers missing value error
        res_empty = subprocess.run(
            [str(SCRIPT_PATH), "--timeout", ""],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_empty.returncode, 1)
        self.assertIn("Missing value for --timeout", res_empty.stderr)

    def test_nonexistent_data_dir_fails(self):
        missing_path = Path(self.temp_dir) / "does_not_exist"
        res = subprocess.run(
            [str(SCRIPT_PATH), "--data-dir", str(missing_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Specified data directory does not exist", res.stderr)


class TestDRStagingSmokeDryRun(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_dr_dryrun_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dry_run_all_services_default(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("[DRY-RUN]", res.stdout)
        self.assertIn("staging-net", res.stdout)

        # Actual Budget assertions
        self.assertIn("actual-server-staging", res.stdout)
        self.assertIn("5006:5006", res.stdout)
        self.assertIn("256m", res.stdout)
        self.assertIn("0.50", res.stdout)
        self.assertIn("actual-stage-data:/data", res.stdout)
        self.assertIn("docker.io/actualbudget/actual-server:26.9.0", res.stdout)
        self.assertIn("http://localhost:5006/", res.stdout)
        self.assertIn("200|302", res.stdout)
        self.assertIn("docker stop actual-server-staging", res.stdout)
        self.assertIn("docker rm -f actual-server-staging", res.stdout)

        # Vaultwarden assertions
        self.assertIn("vaultwarden-staging", res.stdout)
        self.assertIn("7278:80", res.stdout)
        self.assertIn("vw-stage-data:/data", res.stdout)
        self.assertIn("vaultwarden/server:1.35.4", res.stdout)
        self.assertIn("DOMAIN=http://localhost:7278", res.stdout)
        self.assertIn("SIGNUPS_ALLOWED=false", res.stdout)
        self.assertIn("http://localhost:7278/alive", res.stdout)
        self.assertIn("assert HTTP 200 within 30s", res.stdout)
        self.assertIn("docker stop vaultwarden-staging", res.stdout)
        self.assertIn("docker rm -f vaultwarden-staging", res.stdout)

        # Network teardown
        self.assertIn("docker network rm staging-net", res.stdout)

    def test_dry_run_service_actual_only(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "actual", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("actual-server-staging", res.stdout)
        self.assertIn("5006:5006", res.stdout)
        self.assertNotIn("vaultwarden-staging", res.stdout)
        self.assertNotIn("7278:80", res.stdout)

    def test_dry_run_service_vaultwarden_only(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "vaultwarden", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("vaultwarden-staging", res.stdout)
        self.assertIn("7278:80", res.stdout)
        self.assertNotIn("actual-server-staging", res.stdout)
        self.assertNotIn("5006:5006", res.stdout)

    def test_dry_run_with_keep_flag(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run", "--keep"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Skipped (--keep enabled", res.stdout)
        self.assertNotIn("Teardown: docker stop", res.stdout)
        self.assertNotIn("Network Teardown: docker network rm", res.stdout)

    def test_dry_run_with_remote_host(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--host", "bjorn", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Pre-flight: ssh -o BatchMode=yes -o ConnectTimeout=5 bjorn 'echo ok'", res.stdout)
        self.assertIn("ssh bjorn docker network inspect staging-net", res.stdout)
        self.assertIn("ssh bjorn docker run -d --name actual-server-staging", res.stdout)
        self.assertIn("ssh bjorn curl -fsS http://localhost:5006/", res.stdout)
        self.assertIn("ssh bjorn docker run -d --name vaultwarden-staging", res.stdout)
        self.assertIn("ssh bjorn curl -fsS http://localhost:7278/alive", res.stdout)
        self.assertIn("ssh bjorn docker stop actual-server-staging", res.stdout)

    def test_dry_run_with_data_dir(self):
        test_data_dir = Path(self.temp_dir) / "decrypted_data"
        actual_sub = test_data_dir / "actual"
        vw_sub = test_data_dir / "vaultwarden"
        actual_sub.mkdir(parents=True)
        vw_sub.mkdir(parents=True)

        res = subprocess.run(
            [str(SCRIPT_PATH), "--data-dir", str(test_data_dir), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn(f"{actual_sub}:/data", res.stdout)
        self.assertIn(f"{vw_sub}:/data", res.stdout)

    def test_dry_run_with_custom_timeout(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--timeout", "45", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("within 45s", res.stdout)


class TestDRStagingSmokeExecutionAndTraps(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.mkdtemp(prefix="test_dr_exec_")
        self.bin_dir = Path(self.sandbox) / "bin"
        self.log_file = Path(self.sandbox) / "commands.log"
        self.bin_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)

    def _create_mock_binary(self, name: str, script_content: str) -> Path:
        bin_path = self.bin_dir / name
        bin_path.write_text(f"#!/usr/bin/env bash\n{script_content}\n", encoding="utf-8")
        bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC)
        return bin_path

    def test_successful_mocked_execution_with_teardown_trap(self):
        # Mock docker
        self._create_mock_binary("docker", f"""
echo "docker $@" >> "{self.log_file}"
case "$1" in
  network)
    if [[ "$2" == "inspect" ]]; then
      exit 0
    fi
    exit 0
    ;;
  run)
    exit 0
    ;;
  inspect)
    echo "running"
    exit 0
    ;;
  logs)
    echo "Server started listening"
    exit 0
    ;;
  stop|rm)
    exit 0
    ;;
esac
exit 0
""")

        # Mock curl: return HTTP 200
        self._create_mock_binary("curl", f"""
echo "curl $@" >> "{self.log_file}"
echo "200"
exit 0
""")

        env = dict(os.environ)
        env["DOCKER_CMD"] = str(self.bin_dir / "docker")
        env["CURL_CMD"] = str(self.bin_dir / "curl")

        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "actual", "--timeout", "5"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )

        self.assertEqual(res.returncode, 0, f"Script failed with output:\n{res.stdout}\n{res.stderr}")
        self.assertIn("Success: actual endpoint responded with HTTP 200", res.stdout)
        self.assertIn("Disaster Recovery Staging Smoke Test PASSED", res.stdout)

        # Verify command execution log
        log_content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("docker run -d --name actual-server-staging", log_content)
        self.assertIn("curl -s -o /dev/null -w %{http_code} http://localhost:5006/", log_content)
        # Teardown trap executed on exit
        self.assertIn("docker stop actual-server-staging", log_content)
        self.assertIn("docker rm -f actual-server-staging", log_content)

    def test_probe_timeout_triggers_cleanup_trap(self):
        # Mock docker
        self._create_mock_binary("docker", f"""
echo "docker $@" >> "{self.log_file}"
case "$1" in
  inspect)
    echo "running"
    exit 0
    ;;
  logs)
    echo "Listening on port 5006"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""")

        # Mock curl: return 500 continuously
        self._create_mock_binary("curl", f"""
echo "curl $@" >> "{self.log_file}"
echo "500"
exit 0
""")

        env = dict(os.environ)
        env["DOCKER_CMD"] = str(self.bin_dir / "docker")
        env["CURL_CMD"] = str(self.bin_dir / "curl")

        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "actual", "--timeout", "1"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )

        self.assertEqual(res.returncode, 4)
        self.assertIn("Timed out waiting for actual endpoint", res.stderr)

        # Cleanup trap MUST have fired
        log_content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("docker stop actual-server-staging", log_content)
        self.assertIn("docker rm -f actual-server-staging", log_content)

    def test_container_crash_triggers_cleanup_trap(self):
        # Mock docker where inspect reports stopped/exited
        self._create_mock_binary("docker", f"""
echo "docker $@" >> "{self.log_file}"
case "$1" in
  inspect)
    echo "exited"
    exit 0
    ;;
  logs)
    echo "Fatal panic during DB migration"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""")

        # Mock curl: return 000
        self._create_mock_binary("curl", f"""
echo "curl $@" >> "{self.log_file}"
echo "000"
exit 0
""")

        env = dict(os.environ)
        env["DOCKER_CMD"] = str(self.bin_dir / "docker")
        env["CURL_CMD"] = str(self.bin_dir / "curl")

        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "vaultwarden", "--timeout", "3"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )

        self.assertEqual(res.returncode, 4)
        self.assertIn("stopped unexpectedly with status 'exited'", res.stderr)

        # Cleanup trap MUST have fired
        log_content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("docker stop vaultwarden-staging", log_content)
        self.assertIn("docker rm -f vaultwarden-staging", log_content)

    def test_keep_flag_prevents_cleanup_trap_on_failure(self):
        # Mock docker
        self._create_mock_binary("docker", f"""
echo "docker $@" >> "{self.log_file}"
case "$1" in
  inspect)
    echo "running"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""")

        # Mock curl: return 500
        self._create_mock_binary("curl", f"""
echo "curl $@" >> "{self.log_file}"
echo "500"
exit 0
""")

        env = dict(os.environ)
        env["DOCKER_CMD"] = str(self.bin_dir / "docker")
        env["CURL_CMD"] = str(self.bin_dir / "curl")

        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "actual", "--timeout", "1", "--keep"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )

        self.assertEqual(res.returncode, 4)
        self.assertIn("Retention enabled (--keep)", res.stdout)

        log_content = self.log_file.read_text(encoding="utf-8")
        # Ensure post-run stop/rm was NOT called
        lines = log_content.strip().splitlines()
        post_run_ops = [l for l in lines if "docker stop" in l or "docker rm" in l]
        # Pre-cleanup may have run at start before container spin-up, but no stop/rm at end
        # The last command must not be stop or rm
        self.assertFalse(lines[-1].startswith("docker stop"), "Trap should not stop container when --keep is set")
        self.assertFalse(lines[-1].startswith("docker rm"), "Trap should not remove container when --keep is set")

    def test_remote_host_unreachable_exits_2(self):
        # Mock ssh that fails connection
        self._create_mock_binary("ssh", f"""
echo "ssh $@" >> "{self.log_file}"
exit 255
""")

        env = dict(os.environ)
        env["SSH_CMD"] = str(self.bin_dir / "ssh")

        res = subprocess.run(
            [str(SCRIPT_PATH), "--host", "unreachable-host", "--service", "actual"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )

        self.assertEqual(res.returncode, 2)
        self.assertIn("Remote host 'unreachable-host' is unreachable via SSH", res.stderr)


if __name__ == "__main__":
    unittest.main()
