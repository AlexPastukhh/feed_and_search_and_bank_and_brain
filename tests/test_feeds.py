"""Parser and input safety tests run without third-party dependencies."""
import unittest

from info_hub.feeds import MAX_FEED_BYTES, parse_feed, plain_text
from info_hub.fetch import validate_feed_url


RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Example</title>
    <item>
      <guid>post-1</guid><title>RSS &amp; Python</title>
      <link>https://example.org/post-1</link>
      <pubDate>Tue, 03 Nov 2026 12:30:00 GMT</pubDate>
      <description><![CDATA[Short excerpt]]></description>
      <content:encoded><![CDATA[<p>Longer <b>text</b></p><script>evil()</script>]]></content:encoded>
    </item>
  </channel>
</rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example</title>
  <entry>
    <id>tag:example.org,2026:1</id><title>An Atom item</title>
    <link rel="self" href="https://example.org/atom/item.xml"/>
    <link rel="alternate" href="https://example.org/atom/item"/>
    <published>2026-11-03T12:30:00Z</published>
    <author><name>A Person</name></author>
    <summary type="html">&lt;p&gt;Hello world&lt;/p&gt;</summary>
  </entry>
</feed>"""


class FeedParserTests(unittest.TestCase):
    def test_rss_content_and_date(self):
        (entry,) = parse_feed(RSS)
        self.assertEqual(entry.external_id, "post-1")
        self.assertEqual(entry.title, "RSS & Python")
        self.assertEqual(entry.content_text, "Longer text")
        self.assertEqual(entry.content_status, "partial")
        self.assertEqual(entry.published_at.year, 2026)

    def test_atom_prefers_alternate_link(self):
        (entry,) = parse_feed(ATOM)
        self.assertEqual(entry.url, "https://example.org/atom/item")
        self.assertEqual(entry.author, "A Person")
        self.assertEqual(entry.content_text, "Hello world")

    def test_invalid_xml(self):
        with self.assertRaisesRegex(ValueError, "Invalid"):
            parse_feed(b"<rss><invalid>")

    def test_bounded_input(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            parse_feed(b"x" * (MAX_FEED_BYTES + 1))

    def test_html_script_removed(self):
        self.assertEqual(plain_text("<p>Hello</p><script>bad()</script> World"), "Hello World")

    def test_doctype_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "prohibited"):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss/>')


class PublicUrlTests(unittest.TestCase):
    def test_public_domains_allowed_by_syntax(self):
        validate_feed_url("https://example.org/feed.xml")

    def test_local_and_private_ips_blocked(self):
        for url in (
            "http://127.0.0.1/feed",
            "http://localhost/feed",
            "http://printer.local/rss",
            "http://10.0.0.1/feed",
            "http://192.168.1.1/feed",
            "http://[::1]/feed",
            "file:///etc/passwd",
            "http://example.org:8080/feed",
            "https://user:pass@example.org/feed",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_feed_url(url)


if __name__ == "__main__":
    unittest.main()
