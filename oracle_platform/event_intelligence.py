from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

RELIABILITY_TIERS = {
    "official_primary": 1.00,
    "first_party": 0.90,
    "established_journalism": 0.80,
    "specialist": 0.65,
    "social": 0.30,
    "anonymous": 0.10,
    "ai_summary": 0.00,
}


@dataclass(frozen=True, slots=True)
class InformationSource:
    source_id: str
    name: str
    feed_url: str
    reliability_tier: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.name.strip():
            raise ValueError("Source ID and name are required")
        if self.reliability_tier not in RELIABILITY_TIERS:
            raise ValueError("Unknown reliability tier")
        _validate_feed_url(self.feed_url)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    document_id: str
    source_id: str
    source_name: str
    reliability_tier: str
    reliability_weight: float
    title: str
    link: str
    summary: str
    published_at: datetime | None
    observed_at: datetime
    content_hash: str


class RSSIngestor:
    """Fetch explicitly configured HTTPS RSS/Atom feeds with bounded input size.

    The ingestor preserves provenance and hashes entries. It does not interpret a headline
    as confirmed truth, extract claims with an LLM, or map documents to market outcomes.
    """

    def __init__(self, client: httpx.AsyncClient | None = None, max_bytes: int = 2_000_000) -> None:
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False,
            headers={"User-Agent": "ORACLE-private/0.2"},
        )
        self.owns_client = client is None
        self.max_bytes = max_bytes

    async def close(self) -> None:
        if self.owns_client:
            await self.client.aclose()

    async def ingest(self, source: InformationSource) -> list[SourceDocument]:
        if not source.enabled:
            return []
        _validate_feed_url(source.feed_url)
        async with self.client.stream("GET", source.feed_url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise ValueError(f"Feed exceeds {self.max_bytes} byte limit")
                chunks.append(chunk)
        return parse_feed(b"".join(chunks), source, datetime.now(UTC))


def parse_feed(xml_payload: bytes, source: InformationSource,
               observed_at: datetime | None = None) -> list[SourceDocument]:
    if len(xml_payload) > 2_000_000:
        raise ValueError("Feed payload exceeds hard size limit")
    upper_payload = xml_payload[:4096].upper()
    if b"<!DOCTYPE" in upper_payload or b"<!ENTITY" in upper_payload:
        raise ValueError("DTD/entity declarations are not accepted in RSS feeds")
    observed_at = observed_at or datetime.now(UTC)
    try:
        root = ET.fromstring(xml_payload)
    except ET.ParseError as exc:
        raise ValueError("Invalid RSS/Atom XML") from exc
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    if _local_name(root.tag) == "feed":
        entries = root.findall("atom:entry", ns)
    else:
        channel = root.find("channel")
        entries = channel.findall("item") if channel is not None else root.findall("item")
    documents: list[SourceDocument] = []
    for entry in entries:
        title = _child_text(entry, ("title", "{http://www.w3.org/2005/Atom}title"))
        summary = _child_text(entry, (
            "description", "summary", "content", "{http://www.w3.org/2005/Atom}summary",
            "{http://www.w3.org/2005/Atom}content",
        ))
        link = _child_text(entry, ("link",))
        atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
        if atom_link is not None:
            link = atom_link.attrib.get("href", link)
        if not title and not link:
            continue
        published_raw = _child_text(entry, (
            "pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}updated",
        ))
        published = _parse_published(published_raw)
        title = _clean_text(title)
        summary = _clean_text(summary)
        link = html.unescape(link).strip()
        canonical = "\n".join((source.source_id, title.casefold(), link, summary.casefold()))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        documents.append(SourceDocument(
            document_id=digest, source_id=source.source_id, source_name=source.name,
            reliability_tier=source.reliability_tier,
            reliability_weight=RELIABILITY_TIERS[source.reliability_tier],
            title=title, link=link, summary=summary, published_at=published,
            observed_at=observed_at, content_hash=digest,
        ))
    return documents


def _validate_feed_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Only explicitly configured HTTPS feed URLs are permitted")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Embedded URL credentials are not permitted in feed URLs")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal")):
        raise ValueError("Local/internal feed hosts are not permitted")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Non-public IP feed hosts are not permitted")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, tags: tuple[str, ...]) -> str:
    for tag in tags:
        child = element.find(tag)
        if child is not None:
            return " ".join(x for x in child.itertext() if x).strip()
    return ""


def _clean_text(value: str) -> str:
    no_tags = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def _parse_published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
