"""
Configuration loading for cairn-test.

Loads and validates cairn-test.yaml.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

DEFAULT_MASKING_NAMES = [
    "authorization",
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "ssn",
]

DEFAULT_MASKING_PATTERNS = [
    r"(?i)bearer\s+[a-z0-9\-._~+/]+=*",
    r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b",
]

@dataclass
class Config:
    spec: str | None = None
    env_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_env: str = "local"
    masking_names: list[str] = field(default_factory=lambda: list(DEFAULT_MASKING_NAMES))
    masking_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_MASKING_PATTERNS))
    timeout_ms: int = 10000
    parallelism: int = 4

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: Path | None = None) -> Config:
        masking = data.get("masking", {})
        names = masking.get("names", masking.get("secret_names", DEFAULT_MASKING_NAMES))
        patterns = masking.get("patterns", DEFAULT_MASKING_PATTERNS)

        # Resolve env profiles (either inline dict or path to env file)
        raw_envs = data.get("envs", data.get("env_profiles", {}))
        env_profiles: dict[str, dict[str, Any]] = {}
        for env_name, env_val in raw_envs.items():
            if isinstance(env_val, dict):
                env_profiles[env_name] = env_val
            elif isinstance(env_val, str):
                ref_path = (base_dir or Path(".")).resolve() / env_val
                if ref_path.is_file():
                    with open(ref_path, "r", encoding="utf-8") as f:
                        env_profiles[env_name] = yaml.safe_load(f) or {}
                else:
                    env_profiles[env_name] = {"base_url": env_val}

        return cls(
            spec=data.get("spec"),
            env_profiles=env_profiles,
            default_env=data.get("default_env", "local"),
            masking_names=list(names),
            masking_patterns=list(patterns),
            timeout_ms=int(data.get("timeout_ms", 10000)),
            parallelism=int(data.get("parallelism", 4)),
        )

    @classmethod
    def load(cls, path: Path | str | None = None) -> Config:
        """
        Load configuration from the specified path or discover cairn-test.yaml in current directory.
        """
        if path is not None:
            p = Path(path).resolve()
            if not p.is_file():
                raise FileNotFoundError(f"Configuration file not found: {p}")
            with open(p, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            return cls.from_dict(raw, base_dir=p.parent)

        # Default discovery
        for candidate in ["cairn-test.yaml", "cairn-test.yml"]:
            p = Path(candidate).resolve()
            if p.is_file():
                with open(p, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                return cls.from_dict(raw, base_dir=p.parent)

        return cls()
