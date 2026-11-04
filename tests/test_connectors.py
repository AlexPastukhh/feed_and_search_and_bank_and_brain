"""Connector contract tests without network or a database."""
import unittest
from unittest.mock import patch

from info_hub.connectors import get_connector
from info_hub.contracts import SyncBatch
from tests.test_feeds import RSS


class ConnectorTests(unittest.TestCase):
    def test_registry_rejects_unknown_connector(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            get_connector("nonexistent")

    def test_rss_connector_returns_generic_batch(self):
        with patch(
            "info_hub.connectors.fetch_feed",
            return_value=(200, RSS, "etag-1", "Tue, 03 Nov 2026 12:30:00 GMT"),
        ) as fetch:
            batch = get_connector("rss_atom").sync(
                {"feed_url": "https://example.org/rss"},
                etag=None, last_modified=None,
            )
        self.assertIsInstance(batch, SyncBatch)
        self.assertEqual(len(batch.items), 1)
        self.assertEqual(batch.items[0].title, "RSS & Python")
        self.assertEqual(batch.etag, "etag-1")
        fetch.assert_called_once()

    def test_rss_not_modified_creates_no_items(self):
        with patch(
            "info_hub.connectors.fetch_feed",
            return_value=(304, b"", "etag-1", None),
        ):
            batch = get_connector("rss_atom").sync(
                {"feed_url": "https://example.org/rss"},
                etag="etag-1", last_modified=None,
            )
        self.assertEqual(batch.items, [])
        self.assertEqual(batch.etag, "etag-1")


if __name__ == "__main__":
    unittest.main()
