from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


BASE_STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage"


def ensure_profile_directories(profile_id: str) -> dict[str, str]:
    profile_root = BASE_STORAGE_DIR / "profiles" / profile_id
    browser_dir = profile_root / "browser"
    cache_dir = profile_root / "cache"
    cookies_dir = profile_root / "cookies"

    browser_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cookies_dir.mkdir(parents=True, exist_ok=True)

    return {
      "root": str(profile_root),
      "browser": str(browser_dir),
      "cache": str(cache_dir),
      "cookies": str(cookies_dir),
    }


async def save_cookie_upload(profile_id: str, upload: UploadFile) -> tuple[str, str]:
    directories = ensure_profile_directories(profile_id)
    extension = Path(upload.filename or "cookies.txt").suffix or ".txt"
    target_path = Path(directories["cookies"]) / f"{uuid4().hex}{extension}"
    content = await upload.read()
    target_path.write_bytes(content)
    return str(target_path), content.decode("utf-8", errors="ignore")


def save_normalized_cookie_state(profile_id: str, cookies_json: str) -> dict[str, str]:
    directories = ensure_profile_directories(profile_id)
    normalized_path = Path(directories["cookies"]) / "normalized_cookies.json"
    storage_state_path = Path(directories["browser"]) / "storage_state.json"

    normalized_path.write_text(cookies_json, encoding="utf-8")
    storage_state_path.write_text(f'{{"cookies": {cookies_json}, "origins": []}}', encoding="utf-8")

    return {
        "normalized_cookie_path": str(normalized_path),
        "storage_state_path": str(storage_state_path),
    }


def save_storage_state(profile_id: str, cookies_json: str, storage_state: dict[str, object]) -> dict[str, str]:
    directories = ensure_profile_directories(profile_id)
    normalized_path = Path(directories["cookies"]) / "normalized_cookies.json"
    storage_state_path = Path(directories["browser"]) / "storage_state.json"

    normalized_path.write_text(cookies_json, encoding="utf-8")
    storage_state_path.write_text(json.dumps(storage_state, ensure_ascii=True), encoding="utf-8")

    return {
        "normalized_cookie_path": str(normalized_path),
        "storage_state_path": str(storage_state_path),
    }
