from __future__ import annotations

from app.worker.providers.base import ProviderArtifact, ProviderAutomation


class FlowAutomationProvider(ProviderAutomation):
    provider_name = "flow"

    def generate_image(self) -> list[ProviderArtifact]:
        return [
            ProviderArtifact(
                artifact_type="image",
                file_name="flow-image.png",
                mime_type="image/png",
                text_content="\n".join([
                    "FlowGrok Google Flow provider placeholder image artifact",
                    f"prompt={self.context.prompt}",
                    f"profile={self.context.profile_name}",
                    f"headless={self.context.headless}",
                ]),
                metadata={
                    "provider": self.provider_name,
                    "mode": "generate_image",
                    "site": "https://labs.google/flow/",
                },
            )
        ]

    def generate_video(self) -> list[ProviderArtifact]:
        return [
            ProviderArtifact(
                artifact_type="video",
                file_name="flow-video.mp4",
                mime_type="video/mp4",
                text_content="\n".join([
                    "FlowGrok Google Flow provider placeholder video artifact",
                    f"prompt={self.context.prompt}",
                    f"profile={self.context.profile_name}",
                    f"headless={self.context.headless}",
                ]),
                metadata={
                    "provider": self.provider_name,
                    "mode": "generate_video",
                    "site": "https://labs.google/flow/",
                },
            )
        ]
