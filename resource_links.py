"""Validation and small SQL helpers for optional application resources."""

import ipaddress
import re
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
MAX_LABEL_LENGTH = 120
MAX_EMAIL_LINKS = 20
RESOURCE_FIELDS = {"job_posting_url", "application_portal_url", "email_links"}


def validate_url(value, field, optional=False):
    """Accept absolute HTTP(S) links without credentials; never fetch the URL."""
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a URL string" + (" or null." if optional else "."))
    value = value.strip()
    if optional and not value:
        return None
    message = f"{field} must be a valid absolute HTTP or HTTPS URL without credentials."
    if not value or len(value) > MAX_URL_LENGTH:
        raise ValueError(f"{field} must contain 1–{MAX_URL_LENGTH} characters.")
    # urlsplit can silently discard some control characters. Reject them first.
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(message)
    if any(character in value for character in '\\<>"{}|^`') or re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise ValueError(message)
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise ValueError
        if "@" in parsed.netloc or parsed.username is not None or parsed.password is not None:
            raise ValueError
        # urlsplit alone accepts junk after a bracketed IPv6 hostname.
        authority_pattern = r"\[[^\]]+\](?::[0-9]+)?" if parsed.netloc.startswith("[") else r"[^:]+(?::[0-9]+)?"
        if not re.fullmatch(authority_pattern, parsed.netloc):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        if parsed.netloc.endswith(":"):
            raise ValueError
        hostname = parsed.hostname
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            hostname = hostname.encode("idna").decode("ascii").rstrip(".")
            if len(hostname) > 253 or not all(
                re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in hostname.split(".")
            ):
                raise ValueError
    except (ValueError, UnicodeError) as error:
        raise ValueError(message) from error
    return value


def validate_resources(data):
    """Normalize only supplied fields, so PATCH can preserve omitted values."""
    for field in ("job_posting_url", "application_portal_url"):
        if field in data:
            data[field] = validate_url(data[field], field, optional=True)
    if "email_links" not in data:
        return
    links = data["email_links"]
    if not isinstance(links, list) or len(links) > MAX_EMAIL_LINKS:
        raise ValueError(f"email_links must be an array of at most {MAX_EMAIL_LINKS} entries.")
    cleaned = []
    for number, link in enumerate(links, start=1):
        field = f"email_links entry {number}"
        if not isinstance(link, dict) or set(link) != {"label", "url"}:
            raise ValueError(f"{field} must contain exactly label and url.")
        label = link["label"]
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= MAX_LABEL_LENGTH:
            raise ValueError(f"{field} label must contain 1–{MAX_LABEL_LENGTH} characters.")
        cleaned.append({"label": label.strip(), "url": validate_url(link["url"], f"{field} url")})
    data["email_links"] = cleaned


def replace_email_links(connection, application_id, links):
    """Caller owns the transaction, including deletion and replacement."""
    connection.execute("DELETE FROM application_email_links WHERE application_id = ?", (application_id,))
    connection.executemany(
        "INSERT INTO application_email_links (application_id, label, url) VALUES (?, ?, ?)",
        [(application_id, link["label"], link["url"]) for link in links],
    )


def load_email_links(connection, application_ids):
    """Batch reads rather than issuing a query for every application."""
    links = {}
    # Small batches also work on SQLite builds with a low SQL-variable limit.
    for start in range(0, len(application_ids), 500):
        batch = application_ids[start:start + 500]
        placeholders = ", ".join("?" for _ in batch)
        rows = connection.execute(
            "SELECT application_id, label, url FROM application_email_links "
            f"WHERE application_id IN ({placeholders}) ORDER BY id", batch,
        )
        for row in rows:
            links.setdefault(row["application_id"], []).append({"label": row["label"], "url": row["url"]})
    return links
