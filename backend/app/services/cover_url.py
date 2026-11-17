import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_UNSPLASH_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_UNIQUE_LOCAL = ipaddress.ip_network("fc00::/7")
_IMAGE_HOSTS = frozenset({"images.unsplash.com", "plus.unsplash.com"})
_PAGE_HOSTS = frozenset({"unsplash.com", "www.unsplash.com"})
_API_HOST = "api.unsplash.com"


def clean_optional_text(value: object, *, max_len: int, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ValueError(f"{label} must be at most {max_len} characters")
    return cleaned


def require_text(value: object, *, max_len: int, label: str) -> str:
    cleaned = clean_optional_text(value, max_len=max_len, label=label)
    if cleaned is None:
        raise ValueError(f"{label} is required")
    return cleaned


def clean_color(value: object) -> str | None:
    cleaned = clean_optional_text(value, max_len=7, label="Cover color")
    if cleaned is None:
        return None
    if _COLOR.fullmatch(cleaned) is None:
        raise ValueError("Color must be a #RRGGBB hex value")
    return cleaned


def clean_unsplash_id(value: object) -> str:
    cleaned = require_text(value, max_len=64, label="Unsplash id")
    if _UNSPLASH_ID.fullmatch(cleaned) is None:
        raise ValueError("Unsplash id is not valid")
    return cleaned


def clean_https_url(
    value: object,
    *,
    label: str,
    hosts: frozenset[str] | None = None,
) -> str:
    cleaned = require_text(value, max_len=2048, label=label)
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in cleaned):
        raise ValueError(f"{label} is not allowed")
    try:
        parsed = urlparse(cleaned)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} is not allowed") from exc
    if parsed.scheme != "https":
        raise ValueError(f"{label} must use https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not include credentials")
    host = parsed.hostname
    if not host:
        raise ValueError(f"{label} must include a host")
    if port == 0:
        raise ValueError(f"{label} is not allowed")
    if hosts is not None and host not in hosts:
        raise ValueError(f"{label} host is not allowed")
    return cleaned


def clean_unsplash_image_url(value: object) -> str:
    return clean_https_url(value, label="Cover image URL", hosts=_IMAGE_HOSTS)


def with_unsplash_utm(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["utm_source"] = "northstar"
    query["utm_medium"] = "referral"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def clean_unsplash_credit_url(value: object) -> str:
    cleaned = clean_https_url(value, label="Cover credit URL", hosts=_PAGE_HOSTS)
    credited = with_unsplash_utm(cleaned)
    if len(credited) > 2048:
        raise ValueError("Cover credit URL must be at most 2048 characters")
    return credited


def unsplash_download_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = urlparse(cleaned)
        port = parsed.port
    except ValueError:
        return None
    if (
        len(cleaned) > 2048
        or parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname != _API_HOST
        or port not in {None, 443}
    ):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or parts[0] != "photos" or parts[2] != "download":
        return None
    photo_id = parts[1]
    if photo_id in {".", ".."} or _UNSPLASH_ID.fullmatch(photo_id) is None:
        return None
    return cleaned


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return is_blocked_ip(mapped)
        if ip in _UNIQUE_LOCAL:
            return True
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def assert_public_host(url: str) -> None:
    parsed = urlparse(url)
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("Cover image URL is not allowed") from exc
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        raise ValueError("Cover image URL must use https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Cover image URL must not include credentials")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_ip(literal):
            raise ValueError("Cover image URL host is not allowed")
        return
    lowered = host.lower().rstrip(".")
    if (
        lowered == "localhost"
        or lowered.endswith(".localhost")
        or lowered.endswith(".localdomain")
    ):
        raise ValueError("Cover image URL host is not allowed")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Cover image URL could not be checked") from exc
    if not infos:
        raise ValueError("Cover image URL could not be checked")
    for info in infos:
        ip_text = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise ValueError("Cover image URL host is not allowed") from exc
        if is_blocked_ip(ip):
            raise ValueError("Cover image URL host is not allowed")
