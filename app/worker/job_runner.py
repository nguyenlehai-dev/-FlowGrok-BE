from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.core import Job, JobArtifact, Profile, ProfileAntidetectSettings, ProfileRuntimeSettings
from app.services.job_storage import ensure_job_directories, write_job_binary_artifact, write_job_log, write_job_metadata_artifact, write_job_text_artifact
from app.services.profile_storage import ensure_profile_directories
from app.worker.providers import get_provider_automation
from app.worker.providers.base import ProviderArtifact, ProviderAutomation, ProviderAutomationError, ProviderExecutionContext


@dataclass
class WorkerRuntimeConfig:
    worker_id: str
    max_concurrency: int = 1
    headless: bool = True
    max_priority: int = 100


class JobRunner:
    def __init__(self, config: WorkerRuntimeConfig):
        self.config = config

    def describe(self) -> dict[str, object]:
        return {
            "worker_id": self.config.worker_id,
            "max_concurrency": self.config.max_concurrency,
            "headless": self.config.headless,
            "max_priority": self.config.max_priority,
            "status": "idle",
        }

    def run_once(self, db: Session) -> dict[str, object]:
        active_statuses = ["reserved", "booting_browser", "logging_in", "running", "uploading_result"]
        active_count = db.query(Job).filter(
            Job.worker_id == self.config.worker_id,
            Job.status.in_(active_statuses),
        ).count()
        if active_count >= self.config.max_concurrency:
            return {
                "worker_id": self.config.worker_id,
                "status": "busy",
                "detail": "Worker concurrency limit reached",
            }

        candidates = db.query(Job).filter(
            Job.status == "queued",
            Job.priority <= self.config.max_priority,
        ).order_by(Job.priority.asc(), Job.created_at.asc()).all()
        job = None
        for candidate in candidates:
            if not candidate.profile_id:
                job = candidate
                break
            profile_active_count = db.query(Job).filter(
                Job.profile_id == candidate.profile_id,
                Job.status.in_(active_statuses),
            ).count()
            if profile_active_count == 0:
                job = candidate
                break
        if job is None:
            return {
                "worker_id": self.config.worker_id,
                "status": "idle",
                "detail": "No queued job available or all queued profiles are busy",
            }

        self._execute_job(db, job)
        return {
            "worker_id": self.config.worker_id,
            "status": "completed",
            "job_id": job.id,
            "detail": "Job processed successfully",
        }

    def _execute_job(self, db: Session, job: Job) -> None:
        profile = db.query(Profile).filter(Profile.id == job.profile_id).first()
        if profile is None:
            job.status = "failed"
            job.error_logs = "Profile not found"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        runtime_settings = db.query(ProfileRuntimeSettings).filter(ProfileRuntimeSettings.profile_id == profile.id).first()
        antidetect_settings = db.query(ProfileAntidetectSettings).filter(ProfileAntidetectSettings.profile_id == profile.id).first()

        ensure_profile_directories(profile.id)
        profile_directories = ensure_profile_directories(profile.id)
        job_dirs = ensure_job_directories(job.id)

        job.worker_id = self.config.worker_id
        job.status = "booting_browser"
        job.started_at = datetime.now(timezone.utc)
        job.browser_session_path = job_dirs["root"]
        db.commit()

        log_path = write_job_log(
            job.id,
            "worker.log",
            "\n".join([
                f"worker_id={self.config.worker_id}",
                f"profile_id={profile.id}",
                f"provider={job.provider or profile.category}",
                f"job_type={job.job_type}",
                f"headless={runtime_settings.headless if runtime_settings else self.config.headless}",
            ]),
        )

        job.status = "logging_in"
        db.commit()

        request_payload = job.request_payload or {}
        prompt = job.prompt.strip()
        provider = str(job.provider or profile.category or "grok").strip().lower()
        job_type = str(job.job_type or "generate_image").strip().lower()
        execution_context = ProviderExecutionContext(
            job_id=job.id,
            profile_id=profile.id,
            profile_name=profile.name,
            provider=provider,
            job_type=job_type,
            prompt=prompt,
            request_payload=request_payload,
            headless=runtime_settings.headless if runtime_settings else self.config.headless,
            artifacts_dir=job_dirs["artifacts"],
            logs_dir=job_dirs["logs"],
            browser_dir=profile_directories["browser"],
            cache_dir=profile_directories["cache"],
            storage_state_path=(profile.provider_config or {}).get("storage_state_path") if profile.provider_config else None,
            normalized_cookie_path=(profile.provider_config or {}).get("normalized_cookie_path") if profile.provider_config else None,
            runtime_settings=self._serialize_model(runtime_settings),
            antidetect_settings=self._serialize_model(antidetect_settings),
        )
        provider_runtime: ProviderAutomation | None = None
        primary_result_path: str | None = None
        result_manifest: list[dict[str, object]] = []
        cookie_state: dict[str, object] = {}
        login_state: dict[str, object] = {}
        metadata_path: str | None = None
        try:
            provider_runtime = get_provider_automation(execution_context)
            provider_runtime.bootstrap_context()
            cookie_state = provider_runtime.validate_cookies()
            login_state = provider_runtime.login_with_cookies()
            job.status = "running"
            db.commit()
            provider_artifacts = (
                provider_runtime.generate_video()
                if job_type == "generate_video"
                else provider_runtime.generate_image()
            )

            primary_result_path, result_manifest = self._persist_provider_artifacts(db, job.id, provider_artifacts)

            metadata_path = write_job_metadata_artifact(
                job.id,
                "result.json",
                {
                    "job_id": job.id,
                    "provider": provider,
                    "profile_id": profile.id,
                    "profile_name": profile.name,
                    "category": profile.category,
                    "job_type": job_type,
                    "prompt": prompt,
                    "request_payload": request_payload,
                    "runtime_settings": execution_context.runtime_settings,
                    "antidetect_settings": execution_context.antidetect_settings,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "headless": execution_context.headless,
                    "log_path": log_path,
                    "cookie_state": cookie_state,
                    "login_state": login_state,
                    "artifacts": result_manifest,
                },
            )

            job.status = "uploading_result"
            db.commit()

            db.add(JobArtifact(
                job_id=job.id,
                artifact_type="metadata",
                file_path=metadata_path,
                public_url=None,
                mime_type="application/json",
                size_bytes=Path(metadata_path).stat().st_size,
            ))

            job.result_url = primary_result_path
            job.result_payload = {
                "provider": provider,
                "job_type": job_type,
                "artifacts_dir": job_dirs["artifacts"],
                "logs_dir": job_dirs["logs"],
                "headless": execution_context.headless,
                "request_payload": request_payload,
                "artifact_count": len(result_manifest),
            }
            job.error_logs = None
            job.status = "completed"
            job.finished_at = datetime.now(timezone.utc)
            profile.status = "idle"
            profile.last_used_at = datetime.now(timezone.utc)
            db.commit()
        except ProviderAutomationError as exc:
            self._persist_provider_artifacts(db, job.id, exc.artifacts)
            error_log_path = write_job_log(
                job.id,
                "error.log",
                "\n".join([
                    f"code={exc.code}",
                    f"message={exc.message}",
                    f"provider={provider}",
                    f"profile_id={profile.id}",
                ]),
            )
            job.status = "failed"
            job.error_logs = f"{exc.code}: {exc.message} | log={error_log_path}"
            job.result_payload = {
                "provider": provider,
                "job_type": job_type,
                "error_code": exc.code,
                "logs_dir": job_dirs["logs"],
                "artifacts_dir": job_dirs["artifacts"],
            }
            job.finished_at = datetime.now(timezone.utc)
            profile.status = "error"
            db.commit()
        except Exception as exc:
            error_log_path = write_job_log(
                job.id,
                "error.log",
                "\n".join([
                    "code=UNEXPECTED_PROVIDER_ERROR",
                    f"message={exc}",
                    f"provider={provider}",
                    f"profile_id={profile.id}",
                ]),
            )
            job.status = "failed"
            job.error_logs = f"UNEXPECTED_PROVIDER_ERROR: {exc} | log={error_log_path}"
            job.result_payload = {
                "provider": provider,
                "job_type": job_type,
                "error_code": "UNEXPECTED_PROVIDER_ERROR",
                "logs_dir": job_dirs["logs"],
                "artifacts_dir": job_dirs["artifacts"],
            }
            job.finished_at = datetime.now(timezone.utc)
            profile.status = "error"
            db.commit()
        finally:
            if provider_runtime is not None:
                provider_runtime.close()

    @staticmethod
    def _serialize_model(model: object | None) -> dict[str, object] | None:
        if model is None:
            return None
        if not hasattr(model, "__table__"):
            return None

        data: dict[str, object] = {}
        for column in model.__table__.columns:  # type: ignore[attr-defined]
            value = getattr(model, column.name)
            if isinstance(value, datetime):
                data[column.name] = value.isoformat()
            else:
                data[column.name] = value
        return data

    @staticmethod
    def _persist_provider_artifacts(
        db: Session,
        job_id: str,
        provider_artifacts: list[ProviderArtifact],
    ) -> tuple[str | None, list[dict[str, object]]]:
        primary_result_path: str | None = None
        result_manifest: list[dict[str, object]] = []

        for provider_artifact in provider_artifacts:
            if provider_artifact.binary_content is not None:
                artifact_path = write_job_binary_artifact(
                    job_id,
                    provider_artifact.file_name,
                    provider_artifact.binary_content,
                )
            else:
                artifact_path = write_job_text_artifact(
                    job_id,
                    provider_artifact.file_name,
                    provider_artifact.text_content or "",
                )

            db.add(JobArtifact(
                job_id=job_id,
                artifact_type=provider_artifact.artifact_type,
                file_path=artifact_path,
                public_url=None,
                mime_type=provider_artifact.mime_type,
                size_bytes=Path(artifact_path).stat().st_size,
            ))
            if primary_result_path is None and provider_artifact.artifact_type in {"image", "video"}:
                primary_result_path = artifact_path
            result_manifest.append({
                "artifact_type": provider_artifact.artifact_type,
                "file_path": artifact_path,
                "mime_type": provider_artifact.mime_type,
                "metadata": provider_artifact.metadata,
            })

        return primary_result_path, result_manifest
