#!/usr/bin/env python3
"""
Unit tests validating Ephemeral Staging Compose Profiles and Port Allocation Schema.
Verifies Compose profile configuration, port allocations, volume isolation,
resource caps, and documentation integrity across actual/ and vaultwarden/.
"""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestStagingComposeProfiles(unittest.TestCase):
    def setUp(self):
        self.actual_compose_path = REPO_ROOT / "actual" / "compose.yml"
        self.vw_compose_path = REPO_ROOT / "vaultwarden" / "compose.yml"

        with open(self.actual_compose_path, "r", encoding="utf-8") as f:
            self.actual_compose = yaml.safe_load(f)

        with open(self.vw_compose_path, "r", encoding="utf-8") as f:
            self.vw_compose = yaml.safe_load(f)

    def test_actual_staging_service_configuration(self):
        services = self.actual_compose.get("services", {})
        self.assertIn("actual-server-staging", services, "actual-server-staging must be declared in actual/compose.yml")

        staging_svc = services["actual-server-staging"]
        self.assertEqual(staging_svc.get("container_name"), "actual-server-staging")
        self.assertIn("staging", staging_svc.get("profiles", []), "actual-server-staging must have 'staging' profile")
        self.assertEqual(staging_svc.get("restart"), "unless-stopped")

        # Port mapping 5006:5006
        ports = [str(p) for p in staging_svc.get("ports", [])]
        self.assertIn("5006:5006", ports, "actual-server-staging must map host port 5006 to 5006")

        # Volume isolation: actual-stage-data:/data
        volumes = [str(v) for v in staging_svc.get("volumes", [])]
        self.assertTrue(any("actual-stage-data:/data" in v for v in volumes), "Must mount actual-stage-data to /data")

        # Isolated staging network
        networks = staging_svc.get("networks", [])
        self.assertIn("staging-net", networks, "actual-server-staging must attach to staging-net")

        # Resource limits: 256m RAM and 0.50 CPU
        self.assertEqual(staging_svc.get("mem_limit"), "256m", "mem_limit must be 256m")
        self.assertEqual(float(staging_svc.get("cpus")), 0.50, "cpus must be 0.50")

        # Top-level volumes & networks
        top_volumes = self.actual_compose.get("volumes", {})
        self.assertIn("actual-stage-data", top_volumes, "Top-level volumes must declare actual-stage-data")

        top_networks = self.actual_compose.get("networks", {})
        self.assertIn("staging-net", top_networks, "Top-level networks must declare staging-net")

    def test_vaultwarden_staging_service_configuration(self):
        services = self.vw_compose.get("services", {})
        self.assertIn("vaultwarden-staging", services, "vaultwarden-staging must be declared in vaultwarden/compose.yml")

        staging_svc = services["vaultwarden-staging"]
        self.assertEqual(staging_svc.get("container_name"), "vaultwarden-staging")
        self.assertIn("staging", staging_svc.get("profiles", []), "vaultwarden-staging must have 'staging' profile")
        self.assertEqual(staging_svc.get("restart"), "unless-stopped")

        # Port mapping 7278:80
        ports = [str(p) for p in staging_svc.get("ports", [])]
        self.assertIn("7278:80", ports, "vaultwarden-staging must map host port 7278 to 80")

        # Volume isolation: vw-stage-data:/data
        volumes = [str(v) for v in staging_svc.get("volumes", [])]
        self.assertTrue(any("vw-stage-data:/data" in v for v in volumes), "Must mount vw-stage-data to /data")

        # Isolated staging network
        networks = staging_svc.get("networks", [])
        self.assertIn("staging-net", networks, "vaultwarden-staging must attach to staging-net")

        # Resource limits: 256m RAM and 0.50 CPU
        self.assertEqual(staging_svc.get("mem_limit"), "256m", "mem_limit must be 256m")
        self.assertEqual(float(staging_svc.get("cpus")), 0.50, "cpus must be 0.50")

        # Staging environment variables
        env = staging_svc.get("environment", {})
        if isinstance(env, dict):
            self.assertEqual(env.get("DOMAIN"), "http://localhost:7278")
            self.assertEqual(str(env.get("SIGNUPS_ALLOWED")).lower(), "false")
        elif isinstance(env, list):
            self.assertTrue(any("DOMAIN=http://localhost:7278" in str(e) for e in env))
            self.assertTrue(any("SIGNUPS_ALLOWED=false" in str(e) for e in env))
        else:
            self.fail("vaultwarden-staging environment must be a dict or list")

        # Top-level volumes & networks
        top_volumes = self.vw_compose.get("volumes", {})
        self.assertIn("vw-stage-data", top_volumes, "Top-level volumes must declare vw-stage-data")

        top_networks = self.vw_compose.get("networks", {})
        self.assertIn("staging-net", top_networks, "Top-level networks must declare staging-net")

    def test_production_services_have_no_staging_profile(self):
        actual_prod = self.actual_compose["services"]["actual_server"]
        self.assertNotIn("staging", actual_prod.get("profiles", []))

        vw_prod = self.vw_compose["services"]["vaultwarden"]
        self.assertNotIn("staging", vw_prod.get("profiles", []))

    def test_volume_segregation_between_prod_and_staging(self):
        # Actual Budget
        prod_vols = [str(v) for v in self.actual_compose["services"]["actual_server"].get("volumes", [])]
        stage_vols = [str(v) for v in self.actual_compose["services"]["actual-server-staging"].get("volumes", [])]
        self.assertTrue(any("actual-data:" in v for v in prod_vols))
        self.assertTrue(any("actual-stage-data:" in v for v in stage_vols))
        self.assertFalse(any("actual-data:" in v for v in stage_vols))

        # Vaultwarden
        vw_prod_vols = [str(v) for v in self.vw_compose["services"]["vaultwarden"].get("volumes", [])]
        vw_stage_vols = [str(v) for v in self.vw_compose["services"]["vaultwarden-staging"].get("volumes", [])]
        self.assertTrue(any("vw-data:" in v for v in vw_prod_vols))
        self.assertTrue(any("vw-stage-data:" in v for v in vw_stage_vols))
        self.assertFalse(any("vw-data:" in v for v in vw_stage_vols))

    def test_staging_architecture_documentation(self):
        doc_path = REPO_ROOT / "docs" / "STAGING_ARCHITECTURE.md"
        self.assertTrue(doc_path.exists(), "docs/STAGING_ARCHITECTURE.md must exist")

        content = doc_path.read_text(encoding="utf-8")
        self.assertIn("5006", content)
        self.assertIn("7278", content)
        self.assertIn("256m", content)
        self.assertIn("0.50", content)
        self.assertIn("actual-stage-data", content)
        self.assertIn("vw-stage-data", content)
        self.assertIn("staging-net", content)
        self.assertIn("--profile staging", content)

    def test_docker_compose_config_profiles(self):
        if not shutil.which("docker"):
            self.skipTest("Docker binary not found on path")

        # Test Actual without profile
        res_actual_base = subprocess.run(
            ["docker", "compose", "-f", str(self.actual_compose_path), "config"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT)
        )
        self.assertEqual(res_actual_base.returncode, 0, f"docker compose config failed: {res_actual_base.stderr}")
        self.assertNotIn("actual-server-staging:", res_actual_base.stdout)

        # Test Actual with --profile staging
        res_actual_staging = subprocess.run(
            ["docker", "compose", "-f", str(self.actual_compose_path), "--profile", "staging", "config"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT)
        )
        self.assertEqual(res_actual_staging.returncode, 0, f"docker compose --profile staging config failed: {res_actual_staging.stderr}")
        self.assertIn("actual-server-staging:", res_actual_staging.stdout)

        # Test Vaultwarden without profile
        res_vw_base = subprocess.run(
            ["docker", "compose", "-f", str(self.vw_compose_path), "config"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT)
        )
        self.assertEqual(res_vw_base.returncode, 0, f"docker compose config failed: {res_vw_base.stderr}")
        self.assertNotIn("vaultwarden-staging:", res_vw_base.stdout)

        # Test Vaultwarden with --profile staging
        res_vw_staging = subprocess.run(
            ["docker", "compose", "-f", str(self.vw_compose_path), "--profile", "staging", "config"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT)
        )
        self.assertEqual(res_vw_staging.returncode, 0, f"docker compose --profile staging config failed: {res_vw_staging.stderr}")
        self.assertIn("vaultwarden-staging:", res_vw_staging.stdout)


if __name__ == "__main__":
    unittest.main()
