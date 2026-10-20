"""Google Календарь мастера через сервисный аккаунт: мастер делится своим календарём с email
сервисного аккаунта («Внесение изменений»), OAuth и пароли не нужны.
- занятое в календаре закрывает время для записи (freeBusy);
- новая запись появляется событием в календаре, отмена его удаляет.
Любая ошибка Google не ломает запись: календарь — дополнение, а не источник правды."""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
from google.auth import crypt, jwt

from booking.config import settings

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"
_token: tuple[str, float] = ("", 0.0)
_busy_cache: dict[tuple[str, str, str], tuple[float, list]] = {}


def enabled() -> bool:
    return bool(settings.google_credentials_file)


async def _access_token() -> str:
    """OAuth 2.0 для сервисного аккаунта: подписываем JWT своим ключом и меняем его на токен на час."""
    global _token
    if _token[1] > time.time() + 60:
        return _token[0]
    text = await asyncio.to_thread(Path(settings.google_credentials_file).read_text, encoding="utf-8")
    info = json.loads(text)
    now = int(time.time())
    assertion = jwt.encode(
        crypt.RSASigner.from_service_account_info(info),
        {
            "iss": info["client_email"],
            "scope": SCOPE,
            "aud": info["token_uri"],
            "iat": now,
            "exp": now + 3600,
        },
    )
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            info["token_uri"],
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion.decode()},
        )
        r.raise_for_status()
    data = r.json()
    _token = (data["access_token"], now + data["expires_in"])
    return _token[0]


async def _request(method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, API + path, headers={"Authorization": f"Bearer {await _access_token()}"}, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}


async def busy(calendar_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Занятые интервалы календаря. Кэш на минуту: страницу выбора времени открывают часто."""
    key = (calendar_id, start.isoformat(), end.isoformat())
    if (cached := _busy_cache.get(key)) and cached[0] > time.time():
        return cached[1]
    try:
        data = await _request(
            "POST",
            "/freeBusy",
            json={"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": calendar_id}]},
        )
        result = [
            (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
            for b in data["calendars"][calendar_id].get("busy", [])
        ]
    except Exception as e:
        log.warning("Google Календарь %s недоступен: %s", calendar_id, e)
        result = []
    _busy_cache[key] = (time.time() + 60, result)
    return result


async def add_event(calendar_id: str, title: str, details: str, start: datetime, end: datetime) -> str | None:
    try:
        data = await _request(
            "POST",
            f"/calendars/{calendar_id}/events",
            json={
                "summary": title,
                "description": details,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )
        _busy_cache.clear()
        return data.get("id")
    except Exception as e:
        log.warning("Не удалось добавить событие в календарь %s: %s", calendar_id, e)
        return None


async def delete_event(calendar_id: str, event_id: str) -> None:
    try:
        await _request("DELETE", f"/calendars/{calendar_id}/events/{event_id}")
        _busy_cache.clear()
    except Exception as e:
        log.warning("Не удалось удалить событие %s: %s", event_id, e)
