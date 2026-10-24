import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BTCUPDOWN_DIR = REPO_ROOT / "btcupdown"


class TestBtcupdownColocatedStack(unittest.TestCase):
    def test_dockerfile_builds_and_installs_btcupdown_engine(self):
        dockerfile = (BTCUPDOWN_DIR / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("--bin data-broker", dockerfile)
        self.assertIn("--bin btcupdown-engine", dockerfile)
        self.assertIn("--bin vixxy-poller", dockerfile)
        self.assertIn("--bin kalshi-poller", dockerfile)
        self.assertIn("--bin btcupdown-cli", dockerfile)
        self.assertIn("/usr/local/bin/btcupdown-engine", dockerfile)
        self.assertIn("EXPOSE 8080 8081", dockerfile)

    def test_entrypoint_supervises_colocated_engine_sharing_broker_sqlite(self):
        entrypoint = (BTCUPDOWN_DIR / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('BROKER_DB_PATH="${BROKER_DB_PATH:-/data/broker.sqlite}"', entrypoint)
        self.assertIn('ENGINE_DB_PATH="${ENGINE_DB_PATH:-${BROKER_DB_PATH}}"', entrypoint)
        self.assertIn('ENGINE_LISTEN_ADDR="${ENGINE_LISTEN_ADDR:-0.0.0.0:8081}"', entrypoint)
        self.assertIn('http://127.0.0.1:8080/health', entrypoint)
        self.assertNotIn('http://127.0.0.1:8080/healthz', entrypoint)
        self.assertIn('btcupdown-engine "${ENGINE_ARGS[@]}"', entrypoint)
        self.assertIn('--db "${ENGINE_DB_PATH}"', entrypoint)
        self.assertIn('--url "${ENGINE_BROKER_WS_URL}"', entrypoint)
        self.assertIn('--bind "${ENGINE_LISTEN_ADDR}"', entrypoint)

    def test_compose_configures_shared_sqlite_and_control_port(self):
        compose_path = BTCUPDOWN_DIR / "compose.yml"
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        svc = data["services"]["btcupdown"]

        env_list = svc.get("environment", [])
        env_str = "\n".join(str(item) for item in env_list)
        self.assertIn("BROKER_DB_PATH=/data/broker.sqlite", env_str)
        self.assertIn("ENGINE_ENABLE=${ENGINE_ENABLE:-true}", env_str)
        self.assertIn("ENGINE_LISTEN_ADDR=${ENGINE_LISTEN_ADDR:-0.0.0.0:8081}", env_str)
        self.assertIn("ENGINE_DB_PATH=${ENGINE_DB_PATH:-/data/broker.sqlite}", env_str)
        self.assertIn("ENGINE_PARTICIPANT_ID=${ENGINE_PARTICIPANT_ID:-bjorn}", env_str)

        ports = svc.get("ports", [])
        self.assertIn("8085:8080", ports)
        self.assertIn("8086:8081", ports)

        hc_test = " ".join(svc.get("healthcheck", {}).get("test", []))
        self.assertIn("http://127.0.0.1:8080/health", hc_test)
        self.assertIn("http://127.0.0.1:8081/health", hc_test)

    def test_agents_docs_describe_colocated_shared_sqlite_pattern(self):
        agents_md = (BTCUPDOWN_DIR / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("btcupdown-engine", agents_md)
        self.assertIn("/data/broker.sqlite", agents_md)
        self.assertIn("8086", agents_md)
        self.assertIn("v_strategy_standings", agents_md)


if __name__ == "__main__":
    unittest.main()
