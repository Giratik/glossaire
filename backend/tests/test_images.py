from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import images
from backend.main import app

JPEG = b"\xff\xd8\xfftest\xff\xd9"


class ImageTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        directory = patch("backend.images.IMAGE_DIR", self.folder)
        directory.start()
        self.addCleanup(directory.stop)
        images._failures.clear()

    def test_download_once_even_for_concurrent_requests(self):
        response = httpx.Response(200, content=JPEG, request=httpx.Request("GET", "https://example.com"))
        with patch("backend.images.httpx.get", return_value=response) as download:
            with ThreadPoolExecutor(max_workers=4) as executor:
                paths = list(executor.map(images.cached_image, [123] * 4))
            download.assert_called_once()
            self.assertTrue(all(p.read_bytes() == JPEG for p in paths))
            self.assertEqual(list(self.folder.iterdir()), [self.folder / "123.jpg"])

    def test_existing_image_is_reused_without_network(self):
        (self.folder / "123.jpg").write_bytes(JPEG)
        with patch("backend.images.httpx.get") as download:
            self.assertEqual(images.cached_image(123).read_bytes(), JPEG)
            download.assert_not_called()

    def test_invalid_or_failed_download_is_not_cached_and_retries_are_delayed(self):
        for image_id, response in [(1, httpx.Response(200, content=b"<html>error</html>", request=httpx.Request("GET", "https://example.com"))),
                                   (2, httpx.Response(429, request=httpx.Request("GET", "https://example.com")))]:
            with patch("backend.images.httpx.get", return_value=response) as download:
                for _ in range(2):
                    with self.assertRaises(HTTPException) as error:
                        images.cached_image(image_id)
                    self.assertEqual(error.exception.status_code, 503)
                download.assert_called_once()
                self.assertFalse((self.folder / f"{image_id}.jpg").exists())
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_api_uses_first_artwork_and_returns_local_bytes(self):
        path = self.folder / "456.jpg"
        path.write_bytes(JPEG)
        with patch("backend.routes.db") as database, patch("backend.routes.cached_image", return_value=path) as cache:
            database.__getitem__.return_value.find_one.return_value = {"card_images": [{"id": 456}]}
            response = TestClient(app).get("/cards/123/image")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, JPEG)
            cache.assert_called_once_with(456)
            cache.reset_mock()
            database.__getitem__.return_value.find_one.return_value = None
            self.assertEqual(TestClient(app).get("/cards/999/image").status_code, 404)
            cache.assert_not_called()

    def test_alternative_image_and_wrong_card_image(self):
        path = self.folder / "456.jpg"
        path.write_bytes(JPEG)
        with patch("backend.routes.db") as database, patch("backend.routes.cached_image", return_value=path) as cache:
            database.__getitem__.return_value.find_one.return_value = {"card_images": [{"id": 123}, {"id": 456}]}
            client = TestClient(app)
            self.assertEqual(client.get("/cards/123/image", params={"image_id": 456}).status_code, 200)
            cache.assert_called_once_with(456)
            cache.reset_mock()
            self.assertEqual(client.get("/cards/123/image", params={"image_id": 999}).status_code, 422)
            cache.assert_not_called()
