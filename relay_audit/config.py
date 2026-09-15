"""Configuration loading: config.toml, rates.toml, .env keys."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VALID_ROLES = ("reference", "candidate", "peer")
VALID_PROTOCOLS = ("openai", "anthropic")


class ConfigError(Exception):
    """Raised when configuration is missing or contradictory."""


@dataclass
class TestParams:
    warmup: int = 2
    speed_requests: int = 15
    speed_max_tokens: int = 8
    speed_prompt_tokens: int = 120
    cache_prefix_tokens: int = 3000
    cache_max_tokens: int = 8
    cache_warm_passes: int = 3
    cache_ttl_seconds: int = 300
    cache_min_speedup_ratio: float = 1.15
    billing_tolerance_pct: float = 15.0
    timeout_seconds: float = 120.0
    # Retries are deliberately not configurable upward. A retry hides a failure,
    # and the failure rate is itself a measurement result.
    max_retries: int = 0


@dataclass
class Endpoint:
    id: str
    label: str
    role: str
    protocol: str
    base_url: str
    key_env: str
    model: str
    enabled: bool = True
    # Optional: the rate this endpoint charges, used for markup comparison.
    rate: dict | None = None
    api_key: str | None = field(default=None, repr=False)
    demo: bool = False

    @property
    def url(self) -> str:
        if self.protocol == "anthropic":
            return self.base_url.rstrip("/") + "/messages"
        return self.base_url.rstrip("/") + "/chat/completions"

    def require_key(self) -> str:
        if self.demo:
            return "demo-key"
        if not self.api_key:
            raise ConfigError(
                f"endpoint '{self.id}': environment variable {self.key_env} is not set. "
                f"Add it to .env (see .env.example) or set it in the shell."
            )
        return self.api_key


@dataclass
class Config:
    name: str
    stale_after_days: int
    tests: TestParams
    endpoints: list[Endpoint]
    official_rates: dict
    demo: bool = False

    def by_role(self, role: str) -> list[Endpoint]:
        return [e for e in self.endpoints if e.role == role]

    @property
    def reference(self) -> Endpoint | None:
        refs = self.by_role("reference")
        return refs[0] if refs else None

    @property
    def candidate(self) -> Endpoint | None:
        c = self.by_role("candidate")
        return c[0] if c else None


def load_dotenv(path: Path) -> int:
    """Minimal .env loader. Real environment variables win. Returns count loaded."""
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def load_rates(path: Path) -> dict:
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for model, entry in data.items():
        if not entry.get("source") or not entry.get("retrieved"):
            entry["_unverified"] = True
    return data


def load_config(
    config_path: Path,
    rates_path: Path | None = None,
    env_path: Path | None = None,
    demo: bool = False,
    only_ids: list[str] | None = None,
    include_disabled: bool = False,
) -> Config:
    if not config_path.exists():
        raise ConfigError(f"config file not found: {config_path}")

    if env_path is not None:
        load_dotenv(env_path)

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    meta = raw.get("meta", {})
    tests = TestParams(**raw.get("tests", {}))

    endpoints: list[Endpoint] = []
    seen: set[str] = set()
    for item in raw.get("endpoint", []):
        ep = Endpoint(
            id=item["id"],
            label=item.get("label", item["id"]),
            role=item["role"],
            protocol=item.get("protocol", "openai"),
            base_url=item["base_url"],
            key_env=item["key_env"],
            model=item["model"],
            enabled=item.get("enabled", True),
            rate=item.get("rate"),
            demo=demo,
        )
        if ep.id in seen:
            raise ConfigError(f"duplicate endpoint id: {ep.id}")
        seen.add(ep.id)
        if ep.role not in VALID_ROLES:
            raise ConfigError(f"endpoint '{ep.id}': role must be one of {VALID_ROLES}, got '{ep.role}'")
        if ep.protocol not in VALID_PROTOCOLS:
            raise ConfigError(
                f"endpoint '{ep.id}': protocol must be one of {VALID_PROTOCOLS}, got '{ep.protocol}'"
            )
        if not ep.base_url.startswith("http"):
            raise ConfigError(f"endpoint '{ep.id}': base_url must be an absolute URL")
        if not demo:
            ep.api_key = os.environ.get(ep.key_env)
        endpoints.append(ep)

    if not endpoints:
        raise ConfigError("no [[endpoint]] blocks found in config")

    if only_ids:
        wanted = {i.strip().lower() for i in only_ids}
        endpoints = [e for e in endpoints if e.id.lower() in wanted or e.role.lower() in wanted]
        if not endpoints:
            raise ConfigError(f"--endpoint filter matched nothing: {only_ids}")

    if not include_disabled:
        # enabled=false is always honoured, including in demo mode. However the
        # run was launched, a disabled endpoint must not be contacted.
        endpoints = [e for e in endpoints if e.enabled]

    if not demo:
        missing = [e for e in endpoints if not e.api_key]
        if missing:
            listing = "\n".join(f"  - {e.id:12s} needs {e.key_env}" for e in missing)
            raise ConfigError(
                "no API key for:\n" + listing + "\n"
                "Fix: copy .env.example to .env and fill it in, export the variables in the "
                "shell, or run with --demo to validate the harness without spending money."
            )

    if not any(e.role == "reference" for e in endpoints):
        raise ConfigError(
            "no endpoint with role='reference'. A comparison without a reference "
            "endpoint is not a measurement. See README."
        )
    if not any(e.role == "candidate" for e in endpoints):
        raise ConfigError("no endpoint with role='candidate'.")

    return Config(
        name=meta.get("name", config_path.stem),
        stale_after_days=int(meta.get("stale_after_days", 14)),
        tests=tests,
        endpoints=endpoints,
        official_rates=load_rates(rates_path) if rates_path else {},
        demo=demo,
    )
