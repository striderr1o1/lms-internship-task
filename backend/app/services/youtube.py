import re
from urllib.parse import parse_qs, unquote, urlparse

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com"}
_PATH_KINDS = {"embed", "shorts", "live"}


def parse_youtube_video_id(value: str) -> str:
    cleaned = value.strip()
    if _VIDEO_ID.fullmatch(cleaned):
        return cleaned
    if "\\" in cleaned or cleaned.lower().startswith("javascript:"):
        raise ValueError("Invalid YouTube URL")
    try:
        parsed = urlparse(cleaned)
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid YouTube URL") from None
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid YouTube URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid YouTube URL")
    if parsed.scheme == "http" and port not in {None, 80}:
        raise ValueError("Invalid YouTube URL")
    if parsed.scheme == "https" and port not in {None, 443}:
        raise ValueError("Invalid YouTube URL")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    video_id = _video_id(host, parsed.path, parsed.query)
    if video_id is None:
        raise ValueError("Invalid YouTube URL")
    return video_id


def _video_id(host: str, path: str, query: str) -> str | None:
    parts = [unquote(part) for part in path.split("/") if part]
    if host == "youtu.be":
        if len(parts) == 1 and _VIDEO_ID.fullmatch(parts[0]):
            return parts[0]
        return None
    if host == "youtube-nocookie.com":
        return _path_id(parts, "embed")
    if host not in _YOUTUBE_HOSTS or not parts:
        return None
    kind = parts[0].lower()
    if kind == "watch":
        if len(parts) != 1:
            return None
        return _watch_id(query)
    if kind in _PATH_KINDS:
        return _path_id(parts, kind)
    return None


def _path_id(parts: list[str], kind: str) -> str | None:
    if len(parts) != 2 or parts[0].lower() != kind:
        return None
    if _VIDEO_ID.fullmatch(parts[1]):
        return parts[1]
    return None


def _watch_id(query: str) -> str | None:
    values = parse_qs(query, keep_blank_values=False).get("v")
    if not values or not _VIDEO_ID.fullmatch(values[0]):
        return None
    return values[0]
