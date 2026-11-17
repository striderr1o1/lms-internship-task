import ipaddress
import json
import logging
import time
from dataclasses import dataclass
from threading import Lock
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException

from app.core.config import get_settings
from app.services.course_service import COVER_COLUMNS
from app.services.cover_url import (
    assert_public_host,
    clean_color,
    clean_https_url,
    clean_optional_text,
    clean_unsplash_credit_url,
    clean_unsplash_id,
    clean_unsplash_image_url,
    is_blocked_ip,
    require_text,
    unsplash_download_url,
    with_unsplash_utm,
)

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.unsplash.com/search/photos"
_SEARCH_TTL_SECONDS = 15 * 60
_SEARCH_CACHE_LIMIT = 128
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_REDIRECTS = {301, 302, 303, 307, 308}
_IMAGE_OK = {200, 206}

_search_lock = Lock()
_search_cache: dict[tuple[str, int, int], tuple[float, dict]] = {}


def prepare_cover(cover: dict | None) -> tuple[dict[str, str | None], str | None]:
    if cover is None:
        return {column: None for column in COVER_COLUMNS}, None
    if not isinstance(cover, dict):
        raise HTTPException(status_code=422, detail="Cover must be an object")
    try:
        source = cover.get("source")
        alt = clean_optional_text(cover.get("alt"), max_len=500, label="Cover alt text")
        color = clean_color(cover.get("color"))
        blur_hash = clean_optional_text(
            cover.get("blur_hash"),
            max_len=64,
            label="Cover blur hash",
        )
        if source == "generated":
            return _columns(
                image_url=None,
                source="generated",
                alt=alt,
                color=color,
                blur_hash=blur_hash,
                unsplash_id=None,
                credit_name=None,
                credit_url=None,
            ), None
        if source == "url":
            image_url = clean_https_url(cover.get("image_url"), label="Cover image URL")
            assert_public_image(image_url)
            return _columns(
                image_url=image_url,
                source="url",
                alt=alt,
                color=color,
                blur_hash=blur_hash,
                unsplash_id=None,
                credit_name=None,
                credit_url=None,
            ), None
        if source == "unsplash":
            image_url = clean_unsplash_image_url(cover.get("image_url"))
            unsplash_id = clean_unsplash_id(cover.get("unsplash_id"))
            credit_name = require_text(
                cover.get("credit_name"),
                max_len=200,
                label="Cover credit name",
            )
            credit_url = clean_unsplash_credit_url(cover.get("credit_url"))
            download = clean_optional_text(
                cover.get("download_location"),
                max_len=2048,
                label="Cover download location",
            )
            return _columns(
                image_url=image_url,
                source="unsplash",
                alt=alt,
                color=color,
                blur_hash=blur_hash,
                unsplash_id=unsplash_id,
                credit_name=credit_name,
                credit_url=credit_url,
            ), download
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(
        status_code=422,
        detail="Cover source must be unsplash, url, or generated",
    )


def track_unsplash_download(download_location: str | None) -> None:
    try:
        _track_unsplash_download(download_location)
    except Exception as exc:
        logger.warning(
            "unsplash download tracking failed type=%s message=%s",
            type(exc).__name__,
            exc,
        )


def _track_unsplash_download(download_location: str | None) -> None:
    if not download_location:
        return
    key = get_settings().unsplash_access_key.strip()
    if not key:
        return
    target = unsplash_download_url(download_location)
    if target is None:
        logger.warning("unsplash download tracking skipped: location was not accepted")
        return
    status, peer_ok, _body = _unsplash_get(target, key=key, params=None, timeout=4.0)
    if not peer_ok or status >= 400:
        logger.warning("unsplash download tracking failed status=%s", status)


def search_unsplash(query: str, page: int, per_page: int) -> dict:
    key = get_settings().unsplash_access_key.strip()
    if not key:
        raise HTTPException(status_code=503, detail="image_search_unavailable")
    per_page = min(per_page, 12)
    cache_key = (query, page, per_page)
    cached = _search_get(cache_key)
    if cached is not None:
        return cached
    status, peer_ok, body = _unsplash_get(
        _SEARCH_URL,
        key=key,
        params={
            "query": query,
            "page": page,
            "per_page": per_page,
            "orientation": "landscape",
            "content_filter": "high",
        },
        timeout=8.0,
        read_body=True,
    )
    if status != 200 or not peer_ok:
        logger.warning("unsplash search failed status=%s", status)
        raise HTTPException(status_code=503, detail="image_search_unavailable")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        logger.warning("unsplash search failed type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="image_search_unavailable") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail="image_search_unavailable")
    trimmed = _trim_search(payload)
    _search_set(cache_key, trimmed)
    return trimmed


def _unsplash_get(
    url: str,
    *,
    key: str,
    params: dict | None,
    timeout: float,
    read_body: bool = False,
) -> tuple[int, bool, bytes]:
    try:
        assert_public_host(url)
    except ValueError as exc:
        logger.warning("unsplash request skipped: %s", exc)
        return 0, False, b""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            request = client.build_request(
                "GET",
                url,
                params=params,
                headers=_unsplash_headers(key),
            )
            response = client.send(request, stream=True)
            try:
                peer_ok = _response_peer_is_public(response)
                body = response.read() if read_body and peer_ok else b""
                return response.status_code, peer_ok, body
            finally:
                response.close()
    except httpx.HTTPError as exc:
        logger.warning(
            "unsplash request failed type=%s message=%s",
            type(exc).__name__,
            exc,
        )
        return 0, False, b""


def assert_public_image(url: str) -> None:
    current = url
    try:
        with httpx.Client(
            timeout=httpx.Timeout(4.0),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "image/*", "User-Agent": "NorthstarLMS/1.0"},
        ) as client:
            for hop in range(4):
                assert_public_host(current)
                probe = _probe_image(client, current)
                if probe.status_code in _REDIRECTS:
                    if hop == 3:
                        raise HTTPException(
                            status_code=422,
                            detail="Cover image URL redirected too many times",
                        )
                    current = _next_url(current, probe.location)
                    continue
                _assert_image(probe)
                return
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cover image URL could not be checked",
        ) from exc


def _columns(
    *,
    image_url: str | None,
    source: str | None,
    alt: str | None,
    color: str | None,
    blur_hash: str | None,
    unsplash_id: str | None,
    credit_name: str | None,
    credit_url: str | None,
) -> dict[str, str | None]:
    return {
        "cover_image_url": image_url,
        "cover_source": source,
        "cover_alt": alt,
        "cover_color": color,
        "cover_blur_hash": blur_hash,
        "cover_unsplash_id": unsplash_id,
        "cover_credit_name": credit_name,
        "cover_credit_url": credit_url,
    }


def _unsplash_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Client-ID {key}",
        "Accept-Version": "v1",
    }


def _search_get(key: tuple[str, int, int]) -> dict | None:
    now = time.monotonic()
    with _search_lock:
        item = _search_cache.get(key)
        if item is None or item[0] <= now:
            if item is not None:
                _search_cache.pop(key, None)
            return None
        return item[1]


def _search_set(key: tuple[str, int, int], payload: dict) -> None:
    now = time.monotonic()
    with _search_lock:
        expired = [item for item, (expires, _) in _search_cache.items() if expires <= now]
        for item in expired:
            _search_cache.pop(item, None)
        if len(_search_cache) >= _SEARCH_CACHE_LIMIT:
            oldest = min(_search_cache, key=lambda item: _search_cache[item][0])
            _search_cache.pop(oldest, None)
        _search_cache[key] = (now + _SEARCH_TTL_SECONDS, payload)


def _trim_search(payload: dict) -> dict:
    results = []
    for photo in payload.get("results") or []:
        trimmed = _trim_photo(photo)
        if trimmed is not None:
            results.append(trimmed)
    return {
        "total": _as_int(payload.get("total")),
        "total_pages": _as_int(payload.get("total_pages")),
        "results": results,
    }


def _trim_photo(photo: object) -> dict | None:
    if not isinstance(photo, dict):
        return None
    photo_id = photo.get("id")
    urls = photo.get("urls") if isinstance(photo.get("urls"), dict) else {}
    user = photo.get("user") if isinstance(photo.get("user"), dict) else {}
    links = photo.get("links") if isinstance(photo.get("links"), dict) else {}
    user_links = user.get("links") if isinstance(user.get("links"), dict) else {}
    thumb = urls.get("thumb")
    small = urls.get("small")
    regular = urls.get("regular")
    download = links.get("download_location")
    if not isinstance(photo_id, str) or not photo_id:
        return None
    if not all(isinstance(item, str) and item for item in (thumb, small, regular, download)):
        return None
    alt = photo.get("alt_description")
    if not isinstance(alt, str) or not alt.strip():
        alt = photo.get("description")
    if not isinstance(alt, str):
        alt = ""
    name = user.get("name") if isinstance(user.get("name"), str) else ""
    profile = user_links.get("html") if isinstance(user_links.get("html"), str) else ""
    color = photo.get("color") if isinstance(photo.get("color"), str) else None
    blur_hash = photo.get("blur_hash") if isinstance(photo.get("blur_hash"), str) else None
    return {
        "id": photo_id,
        "alt": alt.strip(),
        "color": color,
        "blur_hash": blur_hash,
        "width": _as_int(photo.get("width")),
        "height": _as_int(photo.get("height")),
        "urls": {"thumb": thumb, "small": small, "regular": regular},
        "user": {"name": name, "profile_url": _profile_url(profile)},
        "download_location": download,
    }


def _profile_url(value: str) -> str:
    if not value:
        return with_unsplash_utm("https://unsplash.com/")
    try:
        return clean_unsplash_credit_url(value)
    except ValueError:
        return with_unsplash_utm("https://unsplash.com/")


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


@dataclass(frozen=True)
class _Probe:
    status_code: int
    content_type: str
    content_length: str | None
    content_range: str | None
    location: str | None
    peer_ip: str | None


def _probe_image(client: httpx.Client, url: str) -> _Probe:
    head: _Probe | None
    try:
        head = _send(client, "HEAD", url, None)
    except httpx.HTTPError:
        head = None
    if head is not None:
        _assert_peer(head.peer_ip)
        if head.status_code in _REDIRECTS:
            return head
        if head.status_code in _IMAGE_OK and _is_image(head.content_type):
            return head
    try:
        gotten = _send(client, "GET", url, {"Range": "bytes=0-0"})
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cover image URL could not be checked",
        ) from exc
    _assert_peer(gotten.peer_ip)
    return gotten


def _send(client: httpx.Client, method: str, url: str, headers: dict | None) -> _Probe:
    request = client.build_request(method, url, headers=headers)
    response = client.send(request, stream=True)
    try:
        return _Probe(
            status_code=response.status_code,
            content_type=response.headers.get("content-type") or "",
            content_length=response.headers.get("content-length"),
            content_range=response.headers.get("content-range"),
            location=response.headers.get("location"),
            peer_ip=_peer_ip(response),
        )
    finally:
        response.close()


def _assert_image(probe: _Probe) -> None:
    if probe.status_code not in _IMAGE_OK:
        raise HTTPException(status_code=422, detail="Cover image URL could not be checked")
    if not _is_image(probe.content_type):
        raise HTTPException(status_code=422, detail="Cover image URL must point to an image")
    size = _declared_size(probe)
    if size is not None and size > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="Cover image must be 10 MB or smaller")


def _declared_size(probe: _Probe) -> int | None:
    if probe.content_range:
        if "/" not in probe.content_range:
            raise HTTPException(status_code=422, detail="Cover image URL could not be checked")
        total = probe.content_range.rsplit("/", 1)[-1].strip()
        if total != "*":
            if not total.isdigit():
                raise HTTPException(
                    status_code=422,
                    detail="Cover image URL could not be checked",
                )
            return int(total)
    if probe.content_length is None or probe.content_length == "":
        return None
    if not probe.content_length.strip().isdigit():
        raise HTTPException(status_code=422, detail="Cover image URL could not be checked")
    return int(probe.content_length.strip())


def _is_image(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media.startswith("image/")


def _assert_peer(peer: str | None) -> None:
    if not _peer_text_is_public(peer):
        if peer:
            raise ValueError("Cover image URL host is not allowed")
        raise ValueError("Cover image URL could not be checked")


def _next_url(current: str, location: str | None) -> str:
    if location is None or not location.strip():
        raise HTTPException(status_code=422, detail="Cover image URL could not be checked")
    nxt = urljoin(current, location.strip())
    if len(nxt) > 2048:
        raise HTTPException(
            status_code=422,
            detail="Cover image URL must be at most 2048 characters",
        )
    return nxt


def _response_peer_is_public(response: httpx.Response) -> bool:
    return _peer_text_is_public(_peer_ip(response))


def _peer_text_is_public(peer: str | None) -> bool:
    if not peer:
        return False
    try:
        ip = ipaddress.ip_address(peer.split("%", 1)[0])
    except ValueError:
        return False
    return not is_blocked_ip(ip)


def _peer_ip(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    getter = getattr(stream, "get_extra_info", None)
    if getter is None:
        return None
    try:
        addr = getter("server_addr")
    except Exception:
        return None
    if not addr:
        return None
    return str(addr[0])
