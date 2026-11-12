"""Generate Linux CI-only Compose acceptance using a disposable PostgreSQL service."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml
from safesight.config import ROOT


if __name__ == "__main__":
    url = os.getenv("SAFESIGHT_TEST_DATABASE_URL", "")
    if sys.platform != "linux" or not url.endswith("/safesight_test"):
        raise SystemExit("Linux CI and an explicitly named disposable safesight_test database are required")
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    env = output / "compose-ci.env"
    env.write_text(
        f"DATABASE_URL={url}\nMIGRATION_DATABASE_URL={url}\nSUPABASE_URL=https://auth.example.test\nSUPABASE_PUBLISHABLE_KEY=sb_publishable_ci_fixture\nSECRET_KEY=compose-ci-test-only-session-secret-123456789\nEVALUATION_MODE=true\n",
        encoding="utf-8",
    )
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    for name, service in compose["services"].items():
        service.pop("build", None)
        service.pop("ports", None)
        service["image"] = "safesight:ci"
        service["network_mode"] = "host"
        service["env_file"] = [str(env)]
        if name in ("api", "worker"):
            service["volumes"] = [
                f"{ROOT / 'tests/fixtures/inference-models'}:/app/models:ro",
                "media:/app/artifacts/media",
            ]
    (output / "compose-ci.yaml").write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
