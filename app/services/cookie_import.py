from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


PROVIDER_DOMAIN_RULES = {
    "grok": ["grok.com", ".grok.com", "x.com", ".x.com"],
    "flow": ["labs.google", ".labs.google", "google.com", ".google.com"],
    "dreamina": ["dreamina.capcut.com", ".dreamina.capcut.com", "capcut.com", ".capcut.com"],
}


@dataclass
class CookieImportResult:
    normalized_cookies: list[dict[str, Any]]
    parsed_count: int
    valid_count: int
    invalid_count: int
    message: str
    storage_state: dict[str, Any] | None = None


def _normalize_cookie(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    value = str(item.get("value") or "").strip()
    domain = str(item.get("domain") or "").strip()
    path = str(item.get("path") or "/").strip() or "/"

    if not name or not value or not domain:
        raise ValueError("Cookie must contain name, value and domain")

    normalized = {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
    }

    if "expires" in item and item["expires"] not in (None, ""):
        try:
            normalized["expires"] = int(item["expires"])
        except (TypeError, ValueError):
            pass

    if "httpOnly" in item:
        normalized["httpOnly"] = bool(item["httpOnly"])
    if "secure" in item:
        normalized["secure"] = bool(item["secure"])
    if "sameSite" in item and item["sameSite"]:
        normalized["sameSite"] = str(item["sameSite"])

    return normalized


def _is_cookie_domain_allowed(category: str, domain: str) -> bool:
    allowed_domains = PROVIDER_DOMAIN_RULES.get(category, [])
    normalized_domain = domain.lower().strip()
    return any(
        normalized_domain == allowed or normalized_domain.endswith(allowed.lstrip("."))
        for allowed in allowed_domains
    )


def parse_json_cookie_payload(raw_text: str, category: str) -> CookieImportResult:
    payload = json.loads(raw_text)

    if isinstance(payload, dict) and isinstance(payload.get("cookies"), list):
        cookies = payload["cookies"]
    elif isinstance(payload, list):
        cookies = payload
    else:
        raise ValueError("JSON cookie file must be an array or an object containing a cookies array")

    normalized_cookies: list[dict[str, Any]] = []
    invalid_count = 0

    for item in cookies:
        try:
            normalized = _normalize_cookie(item)
            if not _is_cookie_domain_allowed(category, normalized["domain"]):
                invalid_count += 1
                continue
            normalized_cookies.append(normalized)
        except Exception:
            invalid_count += 1

    return CookieImportResult(
        normalized_cookies=normalized_cookies,
        parsed_count=len(cookies),
        valid_count=len(normalized_cookies),
        invalid_count=invalid_count,
        message="JSON cookie payload normalized",
    )


def parse_storage_state_payload(raw_text: str, category: str) -> CookieImportResult:
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("Storage state file must be a JSON object")

    cookies = payload.get("cookies")
    origins = payload.get("origins")
    if not isinstance(cookies, list):
        raise ValueError("Storage state JSON must contain a cookies array")
    if origins is not None and not isinstance(origins, list):
        raise ValueError("Storage state origins must be an array when present")

    parsed = parse_json_cookie_payload(json.dumps(cookies), category)
    return CookieImportResult(
        normalized_cookies=parsed.normalized_cookies,
        parsed_count=parsed.parsed_count,
        valid_count=parsed.valid_count,
        invalid_count=parsed.invalid_count,
        message="Storage state payload normalized",
        storage_state={
            "cookies": parsed.normalized_cookies,
            "origins": origins or [],
        },
    )


def parse_txt_cookie_payload(raw_text: str, category: str) -> CookieImportResult:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip() and not line.strip().startswith("#")]
    normalized_cookies: list[dict[str, Any]] = []
    invalid_count = 0

    for line in lines:
        parts = line.split("\t")
        try:
            if len(parts) >= 7:
                domain, _flag, path, secure, expires, name, value = parts[:7]
                normalized = _normalize_cookie(
                    {
                        "domain": domain,
                        "path": path,
                        "secure": secure.upper() == "TRUE",
                        "expires": expires,
                        "name": name,
                        "value": value,
                    }
                )
            elif "=" in line:
                name, value = line.split("=", 1)
                provider_domain = PROVIDER_DOMAIN_RULES.get(category, [category])[0]
                normalized = _normalize_cookie(
                    {
                        "domain": provider_domain,
                        "path": "/",
                        "name": name.strip(),
                        "value": value.strip(),
                    }
                )
            else:
                invalid_count += 1
                continue

            if not _is_cookie_domain_allowed(category, normalized["domain"]):
                invalid_count += 1
                continue
            normalized_cookies.append(normalized)
        except Exception:
            invalid_count += 1

    return CookieImportResult(
        normalized_cookies=normalized_cookies,
        parsed_count=len(lines),
        valid_count=len(normalized_cookies),
        invalid_count=invalid_count,
        message="TXT cookie payload normalized",
    )


def validate_profile_cookies(category: str, raw_cookies_json: str | None) -> dict[str, Any]:
    if not raw_cookies_json:
        return {
            "valid": False,
            "parsed_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "message": "No cookies imported",
        }

    try:
        parsed = parse_json_cookie_payload(raw_cookies_json, category)
    except Exception as exc:
        return {
            "valid": False,
            "parsed_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "message": f"Invalid cookie payload: {exc}",
        }

    return {
        "valid": parsed.valid_count > 0,
        "parsed_count": parsed.parsed_count,
        "valid_count": parsed.valid_count,
        "invalid_count": parsed.invalid_count,
        "message": parsed.message,
    }
