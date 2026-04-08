from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProviderArtifact:
    artifact_type: str
    file_name: str
    mime_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    text_content: str | None = None
    binary_content: bytes | None = None


class ProviderAutomationError(Exception):
    def __init__(self, code: str, message: str, artifacts: list[ProviderArtifact] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.artifacts = artifacts or []


@dataclass
class ProviderExecutionContext:
    job_id: str
    profile_id: str
    profile_name: str
    provider: str
    job_type: str
    prompt: str
    request_payload: dict[str, Any]
    headless: bool
    artifacts_dir: str
    logs_dir: str
    browser_dir: str
    cache_dir: str
    storage_state_path: str | None
    normalized_cookie_path: str | None
    runtime_settings: dict[str, Any] | None
    antidetect_settings: dict[str, Any] | None


class ProviderAutomation:
    provider_name = "base"

    def __init__(self, context: ProviderExecutionContext):
        self.context = context

    def validate_cookies(self) -> dict[str, Any]:
        has_cookie_state = bool(self.context.storage_state_path or self.context.normalized_cookie_path)
        return {
            "provider": self.provider_name,
            "has_cookie_state": has_cookie_state,
        }

    def bootstrap_context(self) -> dict[str, Any]:
        Path(self.context.artifacts_dir).mkdir(parents=True, exist_ok=True)
        Path(self.context.logs_dir).mkdir(parents=True, exist_ok=True)
        return {
            "provider": self.provider_name,
            "artifacts_dir": self.context.artifacts_dir,
            "logs_dir": self.context.logs_dir,
        }

    def login_with_cookies(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "status": "simulated",
            "headless": self.context.headless,
        }

    def generate_image(self) -> list[ProviderArtifact]:
        raise NotImplementedError

    def generate_video(self) -> list[ProviderArtifact]:
        raise NotImplementedError

    def close(self) -> None:
        return None
