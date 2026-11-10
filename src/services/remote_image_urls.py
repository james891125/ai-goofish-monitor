"""Validate remote media references without fetching them on the application host."""
import ipaddress
from urllib.parse import urlsplit


def safe_public_https_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    if any(ord(char) < 33 or char == "\\" for char in value):
        return None
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443) or url.fragment:
            return None
        if not host or "." not in host or host.endswith((".localhost", ".local", ".internal", ".invalid", ".test")):
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # Reject numeric IPv4 variants such as 127.1 / hexadecimal hosts.
            if all(part.isdigit() or part.lower().startswith("0x") for part in host.split(".")):
                return None
            return value
    except ValueError:
        pass
    return None
