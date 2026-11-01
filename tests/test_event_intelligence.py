from datetime import datetime, timezone

import pytest

from oracle_platform.event_intelligence import InformationSource, parse_feed


def test_rss_parse_preserves_source_provenance_and_hash():
    source = InformationSource("gov", "Government", "https://example.gov/feed.xml", "official_primary")
    xml = b'''<?xml version="1.0"?><rss version="2.0"><channel><item>
    <title>Official Notice</title><link>https://example.gov/notice</link>
    <description>Primary source &amp; details</description><pubDate>Sun, 01 Nov 2026 10:00:00 GMT</pubDate>
    </item></channel></rss>'''
    docs = parse_feed(xml, source, datetime(2026, 11, 1, 10, 1, tzinfo=timezone.utc))
    assert len(docs) == 1
    assert docs[0].title == "Official Notice"
    assert docs[0].summary == "Primary source & details"
    assert docs[0].reliability_weight == 1.0
    assert docs[0].content_hash == docs[0].document_id


def test_feed_config_rejects_plain_http_and_local_hosts():
    with pytest.raises(ValueError):
        InformationSource("bad", "Bad", "http://example.com/feed", "social")
    with pytest.raises(ValueError):
        InformationSource("bad", "Bad", "https://127.0.0.1/feed", "social")


def test_feed_parser_rejects_dtd_and_entity_declarations():
    source = InformationSource("gov", "Government", "https://example.gov/feed.xml", "official_primary")
    with pytest.raises(ValueError, match="DTD/entity"):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY x "boom">]><rss><channel/></rss>', source)


def test_feed_url_rejects_embedded_credentials():
    import pytest
    with pytest.raises(ValueError, match="credentials"):
        InformationSource("creds", "Credential URL", "https://user:pass@example.com/rss", "specialist")
