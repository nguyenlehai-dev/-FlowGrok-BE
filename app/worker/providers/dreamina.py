from __future__ import annotations

from app.worker.providers.base import ProviderArtifact, ProviderAutomation


class DreaminaAutomationProvider(ProviderAutomation):
    provider_name = "dreamina"

    def generate_image(self) -> list[ProviderArtifact]:
        return [
            ProviderArtifact(
                artifact_type="image",
                file_name="dreamina-image.png",
                mime_type="image/png",
                text_content="\n".join([
                    "FlowGrok Dreamina provider placeholder image artifact",
                    f"prompt={self.context.prompt}",
                    f"profile={self.context.profile_name}",
                    f"headless={self.context.headless}",
                ]),
                metadata={
                    "provider": self.provider_name,
                    "mode": "generate_image",
                    "site": "https://dreamina.capcut.com/",
                },
            )
        ]

    def generate_video(self) -> list[ProviderArtifact]:
        return [
            ProviderArtifact(
                artifact_type="video",
                file_name="dreamina-video.mp4",
                mime_type="video/mp4",
                text_content="\n".join([
                    "FlowGrok Dreamina provider placeholder video artifact",
                    f"prompt={self.context.prompt}",
                    f"profile={self.context.profile_name}",
                    f"headless={self.context.headless}",
                ]),
                metadata={
                    "provider": self.provider_name,
                    "mode": "generate_video",
                    "site": "https://dreamina.capcut.com/",
                },
            )
        ]
