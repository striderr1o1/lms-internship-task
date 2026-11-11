import hashlib
import hmac
import json
import logging
import time

import httpx
import psycopg
from fastapi import HTTPException

from app.core.config import get_settings
from app.db import database_error, execute, query_one

_ASSET_COLUMNS = ("mux_asset_id", "playback_id", "status")

logger = logging.getLogger(__name__)

_MUX = "https://api.mux.com"
_NOT_CONFIGURED = "Video upload is not configured"
_PROVIDER = "Video provider request failed"


def create_upload(teacher_id: str) -> dict:
    _require_mux_keys()
    settings = get_settings()
    response = httpx.post(
        f"{_MUX}/video/v1/uploads",
        auth=(settings.mux_token_id, settings.mux_token_secret),
        json={
            "cors_origin": settings.frontend_origin,
            "timeout": 3600,
            "new_asset_settings": {
                "playback_policies": ["public"],
                "video_quality": "basic",
            },
        },
        timeout=30,
    )
    data = _mux_data(response)
    upload_id = data.get("id")
    upload_url = data.get("url")
    if not isinstance(upload_id, str) or not isinstance(upload_url, str):
        raise HTTPException(status_code=502, detail=_PROVIDER)
    try:
        inserted = query_one(
            """
            insert into mux_assets (teacher_id, upload_id, status)
            values (%s, %s, 'waiting')
            returning id
            """,
            (teacher_id, upload_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if inserted is None:
        raise HTTPException(status_code=500, detail="Database request failed")
    return {"id": inserted["id"], "upload_url": upload_url}


def get_video(teacher_id: str, video_id: str) -> dict:
    row = _owned_asset(teacher_id, video_id)
    if row["status"] not in {"ready", "errored"}:
        _require_mux_keys()
        row = _refresh(row)
    return {
        "id": row["id"],
        "status": row["status"],
        "playback_id": row.get("playback_id"),
    }


def handle_webhook(raw_body: bytes, signature: str | None) -> None:
    settings = get_settings()
    if not settings.mux_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook is not configured")
    timestamp, signatures = _parse_signature(signature)
    try:
        issued_at = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid signature") from exc
    if abs(time.time() - issued_at) > 300:
        raise HTTPException(status_code=401, detail="Invalid signature")
    if not _signature_matches(settings.mux_webhook_secret, timestamp, raw_body, signatures):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict):
        return
    data = event.get("data")
    if not isinstance(data, dict):
        data = {}
    event_type = event.get("type")
    if event_type == "video.upload.asset_created":
        _on_asset_created(data)
    elif event_type == "video.asset.ready":
        _on_asset_ready(data)
    elif event_type == "video.asset.errored":
        _on_asset_errored(data)


def _require_mux_keys() -> None:
    settings = get_settings()
    if not settings.mux_token_id or not settings.mux_token_secret:
        raise HTTPException(status_code=503, detail=_NOT_CONFIGURED)


def _refresh(row: dict) -> dict:
    upload = _mux_get(f"/video/v1/uploads/{row['upload_id']}")
    if upload is None:
        return row

    updates: dict = {}
    asset_id = upload.get("asset_id") or row.get("mux_asset_id")
    if isinstance(upload.get("asset_id"), str) and upload["asset_id"] != row.get("mux_asset_id"):
        updates["mux_asset_id"] = upload["asset_id"]
        if row["status"] == "waiting":
            updates["status"] = "asset_created"

    if isinstance(asset_id, str) and asset_id:
        asset = _mux_get(f"/video/v1/assets/{asset_id}")
        if asset is not None:
            status = asset.get("status")
            if status == "ready":
                playbacks = asset.get("playback_ids") or []
                playback_id = None
                if playbacks and isinstance(playbacks[0], dict):
                    playback_id = playbacks[0].get("id")
                updates["mux_asset_id"] = asset_id
                updates["status"] = "ready"
                updates["playback_id"] = playback_id
            elif status == "errored":
                updates["status"] = "errored"

    if not updates:
        return row
    return _save(row, updates)


def _save(row: dict, updates: dict) -> dict:
    columns = [column for column in _ASSET_COLUMNS if column in updates]
    if not columns:
        return row
    assignments = ", ".join(f"{column} = %s" for column in columns)
    params = [updates[column] for column in columns]
    params.append(row["id"])
    try:
        execute(
            f"update mux_assets set {assignments} where id = %s",
            tuple(params),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    for column in columns:
        row[column] = updates[column]
    return row


def _mux_get(path: str) -> dict | None:
    settings = get_settings()
    try:
        response = httpx.get(
            f"{_MUX}{path}",
            auth=(settings.mux_token_id, settings.mux_token_secret),
            timeout=30,
        )
    except httpx.HTTPError as exc:
        logger.warning("mux request failed path=%s", path)
        raise HTTPException(status_code=502, detail=_PROVIDER) from exc
    if response.status_code == 404:
        return None
    return _mux_data(response)


def _mux_data(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=_PROVIDER)
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=_PROVIDER) from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail=_PROVIDER)
    return data


def _owned_asset(teacher_id: str, video_id: str) -> dict:
    try:
        found = query_one(
            """
            select id, teacher_id, upload_id, mux_asset_id, playback_id, status
            from mux_assets
            where id = %s
            """,
            (video_id,),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    if found is None or str(found["teacher_id"]) != str(teacher_id):
        raise HTTPException(status_code=404, detail="Not found")
    return found


def _on_asset_created(data: dict) -> None:
    upload_id = data.get("id")
    asset_id = data.get("asset_id")
    if not isinstance(upload_id, str) or not isinstance(asset_id, str):
        return
    try:
        execute(
            """
            update mux_assets
            set mux_asset_id = %s,
                status = 'asset_created'
            where upload_id = %s
              and status in ('waiting', 'asset_created')
            """,
            (asset_id, upload_id),
        )
    except psycopg.Error as exc:
        raise database_error(exc) from exc


def _on_asset_ready(data: dict) -> None:
    row = _find_asset(data.get("upload_id"), data.get("id"))
    if row is None:
        return
    playback_id = _public_playback_id(data)
    updates = {"status": "ready", "playback_id": playback_id}
    if isinstance(data.get("id"), str):
        updates["mux_asset_id"] = data["id"]
    _save(row, updates)


def _on_asset_errored(data: dict) -> None:
    row = _find_asset(data.get("upload_id"), data.get("id"))
    if row is None:
        return
    _save(row, {"status": "errored"})


def _find_asset(upload_id: object, mux_asset_id: object) -> dict | None:
    try:
        if isinstance(upload_id, str) and upload_id:
            found = query_one(
                """
                select id
                from mux_assets
                where upload_id = %s
                """,
                (upload_id,),
            )
            if found:
                return found
        if isinstance(mux_asset_id, str) and mux_asset_id:
            return query_one(
                """
                select id
                from mux_assets
                where mux_asset_id = %s
                """,
                (mux_asset_id,),
            )
    except psycopg.Error as exc:
        raise database_error(exc) from exc
    return None


def _public_playback_id(data: dict) -> str | None:
    playbacks = data.get("playback_ids") or []
    if not isinstance(playbacks, list):
        return None
    for item in playbacks:
        if isinstance(item, dict) and item.get("policy") == "public" and item.get("id"):
            return item["id"]
    return None


def _parse_signature(header: str | None) -> tuple[str | None, list[str]]:
    if not header:
        raise HTTPException(status_code=401, detail="Invalid signature")
    timestamp = None
    signatures: list[str] = []
    for part in header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "t":
            timestamp = value
        elif key == "v1" and value:
            signatures.append(value.lower())
    if timestamp is None or not signatures:
        raise HTTPException(status_code=401, detail="Invalid signature")
    return timestamp, signatures


def _signature_matches(secret: str, timestamp: str, raw_body: bytes, signatures: list[str]) -> bool:
    signed = f"{timestamp}.".encode() + raw_body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(digest, signature) for signature in signatures)
