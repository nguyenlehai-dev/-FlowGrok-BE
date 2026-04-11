from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

from app.worker.providers.base import ProviderArtifact, ProviderAutomation, ProviderAutomationError


class GrokGatewayProvider(ProviderAutomation):
    provider_name = "grok_gateway"

    def bootstrap_context(self) -> dict[str, Any]:
        super().bootstrap_context()
        endpoint = os.getenv("GROK_GATEWAY_ENDPOINT", "").strip()
        api_key = os.getenv("GROK_GATEWAY_API_KEY", "").strip()
        if not endpoint or not api_key:
            raise ProviderAutomationError(
                "GATEWAY_NOT_CONFIGURED",
                "Grok gateway mode requires GROK_GATEWAY_ENDPOINT and GROK_GATEWAY_API_KEY",
            )
        return {
            "provider": self.provider_name,
            "mode": "gateway",
            "endpoint": endpoint,
        }

    def validate_cookies(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "mode": "gateway",
            "uses_cookie_session": False,
        }

    def login_with_cookies(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "mode": "gateway",
            "status": "not_required",
        }

    def generate_image(self) -> list[ProviderArtifact]:
        return self._call_gateway("generate_image")

    def generate_video(self) -> list[ProviderArtifact]:
        return self._call_gateway("generate_video")

    def _call_gateway(self, mode: str) -> list[ProviderArtifact]:
        endpoint = os.environ["GROK_GATEWAY_ENDPOINT"].rstrip("/")
        api_key = os.environ["GROK_GATEWAY_API_KEY"]
        payload = {
            "job_type": mode,
            "prompt": self.context.prompt,
            "request_payload": self.context.request_payload or {},
        }
        try:
            response = httpx.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
            )
            response.raise_for_status()
        except Exception as exc:
            raise ProviderAutomationError(
                "GATEWAY_REQUEST_FAILED",
                f"Grok gateway request failed: {exc}",
            ) from exc

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            return self._artifacts_from_json(mode, response.json())

        artifact_type = "video" if mode == "generate_video" else "image"
        extension = ".mp4" if mode == "generate_video" else ".bin"
        return [
            ProviderArtifact(
                artifact_type=artifact_type,
                file_name=f"grok-gateway-{mode}{extension}",
                mime_type=content_type or "application/octet-stream",
                binary_content=response.content,
                metadata={"provider": self.provider_name, "mode": mode},
            )
        ]

    def _artifacts_from_json(self, mode: str, data: dict[str, Any]) -> list[ProviderArtifact]:
        artifacts: list[ProviderArtifact] = [
            ProviderArtifact(
                artifact_type="metadata",
                file_name=f"grok-gateway-{mode}.json",
                mime_type="application/json",
                text_content=httpx.Response(200, json=data).text,
                metadata={"provider": self.provider_name, "mode": mode},
            )
        ]

        result_url = data.get("result_url") or data.get("url")
        if isinstance(result_url, str) and result_url:
            try:
                media_response = httpx.get(result_url, timeout=300)
                media_response.raise_for_status()
            except Exception as exc:
                raise ProviderAutomationError(
                    "GATEWAY_RESULT_DOWNLOAD_FAILED",
                    f"Grok gateway result download failed: {exc}",
                    artifacts=artifacts,
                ) from exc
            mime_type = media_response.headers.get("content-type", "application/octet-stream")
            artifacts.append(
                ProviderArtifact(
                    artifact_type="video" if mode == "generate_video" else "image",
                    file_name=f"grok-gateway-{mode}{_extension_for_mime(mime_type)}",
                    mime_type=mime_type,
                    binary_content=media_response.content,
                    metadata={"provider": self.provider_name, "mode": mode, "result_url": result_url},
                )
            )
            return artifacts

        result_base64 = data.get("result_base64")
        if isinstance(result_base64, str) and result_base64:
            mime_type = str(data.get("mime_type") or "application/octet-stream")
            artifacts.append(
                ProviderArtifact(
                    artifact_type="video" if mode == "generate_video" else "image",
                    file_name=f"grok-gateway-{mode}{_extension_for_mime(mime_type)}",
                    mime_type=mime_type,
                    binary_content=base64.b64decode(result_base64),
                    metadata={"provider": self.provider_name, "mode": mode},
                )
            )
            return artifacts

        file_path = data.get("file_path")
        if isinstance(file_path, str) and file_path and Path(file_path).exists():
            path = Path(file_path)
            artifacts.append(
                ProviderArtifact(
                    artifact_type="video" if mode == "generate_video" else "image",
                    file_name=path.name,
                    mime_type=str(data.get("mime_type") or "application/octet-stream"),
                    binary_content=path.read_bytes(),
                    metadata={"provider": self.provider_name, "mode": mode, "file_path": file_path},
                )
            )
            return artifacts

        raise ProviderAutomationError(
            "GATEWAY_RESULT_EMPTY",
            "Grok gateway response did not include result_url, result_base64, file_path, or binary content",
            artifacts=artifacts,
        )


def _extension_for_mime(mime_type: str) -> str:
    if "video" in mime_type:
        return ".mp4"
    if "png" in mime_type:
        return ".png"
    if "jpeg" in mime_type or "jpg" in mime_type:
        return ".jpg"
    if "webp" in mime_type:
        return ".webp"
    return ".bin"
