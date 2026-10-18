import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bson import ObjectId
from fastapi.testclient import TestClient

from backend.main import app


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.entry_id = ObjectId()
        self.payload = dict(set_code="LOB-FR001", condition="Good", language="FR",
                            quantity=2)
        self.mock_patch = patch("backend.routes.collection_db")
        self.db = self.mock_patch.start()
        self.addCleanup(self.mock_patch.stop)
        catalog_patch = patch("backend.routes.db")
        catalog_patch.start()
        self.addCleanup(catalog_patch.stop)
        self.db.find_one.return_value = {"card_id": 123, "set_code": "LOB-FR001"}

    def test_list_exposes_entry_id(self):
        self.db.find.return_value = [{"_id": self.entry_id, "card_id": 123, "quantity": 2}]
        response = self.client.get("/collection")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["collection"][0]["id"], str(self.entry_id))
        self.assertNotIn("_id", response.json()["collection"][0])

    def test_download_status_checks_selected_and_default_images_without_downloading(self):
        self.db.find.return_value = [
            {"_id": ObjectId(), "card_id": 123, "image_id": 456},
            {"_id": ObjectId(), "card_id": 123, "image_id": 789},
            {"_id": ObjectId(), "card_id": 123},
            {"_id": ObjectId(), "card_id": 999},
        ]
        with TemporaryDirectory() as folder, patch("backend.images.IMAGE_DIR", Path(folder)), patch("backend.routes.db") as database, patch("backend.images.httpx.get") as download:
            (Path(folder) / "456.jpg").write_bytes(b"image")
            (Path(folder) / "123.jpg").write_bytes(b"image")
            (Path(folder) / "789.jpg").write_bytes(b"")
            database.__getitem__.return_value.find.return_value = [{"id": 123, "card_images": [{"id": 123}]}]
            cards = self.client.get("/collection").json()["collection"]
            self.assertEqual([c["image_downloaded"] for c in cards], [True, False, True, False])
            (Path(folder) / "456.jpg").unlink()
            self.assertFalse(self.client.get("/collection").json()["collection"][0]["image_downloaded"])
            download.assert_not_called()

    def test_update_targets_only_selected_entry_and_preserves_identity(self):
        self.db.update_one.return_value = SimpleNamespace(matched_count=1, modified_count=0)
        response = self.client.put(f"/collection/{self.entry_id}", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.db.update_one.assert_called_once_with({"_id": self.entry_id}, {"$set": self.payload, "$unset": {"purchase_price": ""}})

    def test_invalid_updates_never_write(self):
        for changes in ({"quantity": 0}, {"quantity": 1.5}, {"purchase_price": -1},
                        {"set_code": "  "}, {"card_id": 456}, {"added_at": "2026-01-01"}):
            with self.subTest(changes=changes):
                response = self.client.put(f"/collection/{self.entry_id}", json=self.payload | changes)
                self.assertEqual(response.status_code, 422)
        self.db.update_one.assert_not_called()

    def test_missing_entries(self):
        self.db.update_one.return_value = SimpleNamespace(matched_count=0)
        self.db.delete_one.return_value = SimpleNamespace(deleted_count=0)
        self.assertEqual(self.client.put(f"/collection/{self.entry_id}", json=self.payload).status_code, 404)
        self.assertEqual(self.client.delete(f"/collection/{self.entry_id}").status_code, 404)

    def test_invalid_ids_never_write(self):
        self.assertEqual(self.client.put("/collection/invalid", json=self.payload).status_code, 400)
        self.assertEqual(self.client.delete("/collection/invalid").status_code, 400)
        self.db.update_one.assert_not_called()
        self.db.delete_one.assert_not_called()

    def test_delete_targets_only_selected_entry(self):
        self.db.delete_one.return_value = SimpleNamespace(deleted_count=1)
        response = self.client.delete(f"/collection/{self.entry_id}")
        self.assertEqual(response.status_code, 200)
        self.db.delete_one.assert_called_once_with({"_id": self.entry_id})

    def test_catalog_set_validation_on_add(self):
        card = json.loads((Path(__file__).resolve().parents[2] / "dummy" / "dark_magician_extracted_infos.json").read_text(encoding="utf-8"))
        payload = dict(card_id=card["id"], card_name=card["name"], **self.payload)
        payload["set_code"] = card["card_sets"][0]["set_code"]
        with patch("backend.routes.db") as database:
            database.__getitem__.return_value.find_one.return_value = card
            self.db.find_one_and_update.return_value = {"_id": self.entry_id, "quantity": 2}
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 200)
            self.db.find_one_and_update.reset_mock()
            for invalid in ("INVENTED-001", "CT13-FR003"):
                self.assertEqual(self.client.post("/collection/add", json=payload | {"set_code": invalid}).status_code, 422)
            database.__getitem__.return_value.find_one.return_value = None
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 422)
            database.__getitem__.return_value.find_one.return_value = {"id": card["id"]}
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 422)
            self.db.find_one_and_update.assert_not_called()

    def test_changed_set_code_is_checked_against_own_card(self):
        with patch("backend.routes.db") as database:
            catalog = database.__getitem__.return_value
            catalog.find_one.return_value = {"card_sets": [{"set_code": "VALID-001"}]}
            self.db.update_one.return_value = SimpleNamespace(matched_count=1)
            response = self.client.put(f"/collection/{self.entry_id}", json=self.payload | {"set_code": "VALID-001"})
            self.assertEqual(response.status_code, 200)
            catalog.find_one.assert_called_with({"id": 123}, {"card_sets": 1})
            self.db.update_one.reset_mock()
            response = self.client.put(f"/collection/{self.entry_id}", json=self.payload | {"set_code": "INVALID-001"})
            self.assertEqual(response.status_code, 422)
            self.db.update_one.assert_not_called()

    def test_artwork_id_saved_and_validated_on_add(self):
        with patch("backend.routes.db") as database:
            database.__getitem__.return_value.find_one.return_value = {
                "card_sets": [{"set_code": self.payload["set_code"]}],
                "card_images": [{"id": 123}, {"id": 456}],
            }
            self.db.find_one_and_update.return_value = {"_id": self.entry_id, "quantity": 2}
            payload = self.payload | {"card_id": 123, "card_name": "Test", "image_id": 456}
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 200)
            self.assertEqual(self.db.find_one_and_update.call_args.args[1]["$set"]["image_id"], 456)
            self.db.find_one_and_update.reset_mock()
            self.assertEqual(self.client.post("/collection/add", json=payload | {"image_id": 999}).status_code, 422)
            self.db.find_one_and_update.assert_not_called()

    def test_editing_other_fields_preserves_artwork(self):
        self.db.find_one.return_value = {"card_id": 123, "set_code": self.payload["set_code"], "image_id": 456}
        self.db.update_one.return_value = SimpleNamespace(matched_count=1)
        self.assertEqual(self.client.put(f"/collection/{self.entry_id}", json=self.payload).status_code, 200)
        self.assertNotIn("image_id", self.db.update_one.call_args.args[1]["$set"])

    def test_add_increments_quantity_and_matches_legacy_default_artwork(self):
        with patch("backend.routes.db") as database:
            database.__getitem__.return_value.find_one.return_value = {
                "card_sets": [{"set_code": self.payload["set_code"]}],
                "card_images": [{"id": 123}, {"id": 456}],
            }
            self.db.find_one_and_update.return_value = {"_id": self.entry_id, "quantity": 5}
            payload = self.payload | {"card_id": 123, "card_name": "Test", "image_id": 123}
            response = self.client.post("/collection/add", json=payload)
            self.assertEqual(response.json()["quantity"], 5)
            identity, update = self.db.find_one_and_update.call_args.args
            self.assertEqual(identity, {"card_id": 123, "set_code": "LOB-FR001", "language": "FR",
                                        "condition": "Good", "rarity": None, "image_id": {"$in": [None, 123]}})
            self.assertEqual(update["$inc"], {"quantity": 2})
            self.assertNotIn("quantity", update["$setOnInsert"])
            self.assertNotIn("added_at", update.get("$set", {}))
            self.client.post("/collection/add", json=payload | {"image_id": 456})
            self.assertEqual(self.db.find_one_and_update.call_args.args[0]["image_id"], 456)
            self.db.find_one_and_update.reset_mock()
            self.assertEqual(self.client.post("/collection/add", json=payload | {"quantity": 0}).status_code, 422)
            self.db.find_one_and_update.assert_not_called()

    def test_edit_artwork_validates_and_saves_selection(self):
        self.db.update_one.return_value = SimpleNamespace(matched_count=1)
        with patch("backend.routes.db") as database:
            database.__getitem__.return_value.find_one.return_value = {"card_images": [{"id": 123}, {"id": 456}, {"id": 456}]}
            options = self.client.get("/cards/123/illustrations")
            self.assertEqual(options.json()["image_ids"], [123, 456])
            result = self.client.put(f"/collection/{self.entry_id}", json=self.payload | {"image_id": 456})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(self.db.update_one.call_args.args[1]["$set"]["image_id"], 456)
            self.db.update_one.reset_mock()
            result = self.client.put(f"/collection/{self.entry_id}", json=self.payload | {"image_id": 999})
            self.assertEqual(result.status_code, 422)
            self.db.update_one.assert_not_called()

    def test_rarity_validation_and_duplicate_identity(self):
        with patch("backend.routes.db") as database:
            database["catalog"].find_one.return_value = {
                "card_sets": [{"set_code": "LOB-FR001", "set_rarity": "Rare"},
                              {"set_code": "LOB-FR001", "set_rarity": "Ultra Rare"}],
                "card_images": [{"id": 123}],
            }
            self.db.find_one_and_update.return_value = {"_id": self.entry_id, "quantity": 2}
            payload = self.payload | {"card_id": 123, "card_name": "Test", "rarity": "Rare"}
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 200)
            self.assertEqual(self.db.find_one_and_update.call_args.args[0]["rarity"], "Rare")
            self.assertEqual(self.db.find_one_and_update.call_args.args[1]["$setOnInsert"]["rarity"], "Rare")
            self.client.post("/collection/add", json=payload | {"rarity": "Ultra Rare"})
            self.assertEqual(self.db.find_one_and_update.call_args.args[0]["rarity"], "Ultra Rare")
            self.db.find_one_and_update.reset_mock()
            self.assertEqual(self.client.post("/collection/add", json=payload | {"rarity": "Secret Rare"}).status_code, 422)
            self.db.find_one_and_update.assert_not_called()
            self.db.update_one.return_value = SimpleNamespace(matched_count=1)
            self.assertEqual(self.client.put(f"/collection/{self.entry_id}", json=self.payload | {"rarity": "Rare"}).status_code, 200)
            self.assertEqual(self.db.update_one.call_args.args[1]["$set"]["rarity"], "Rare")


if __name__ == "__main__":
    unittest.main()
