import unittest
import json
from pathlib import Path
from types import SimpleNamespace
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
        self.db.find_one.return_value = {"card_id": 123, "set_code": "LOB-FR001"}

    def test_list_exposes_entry_id(self):
        self.db.find.return_value = [{"_id": self.entry_id, "card_id": 123, "quantity": 2}]
        response = self.client.get("/collection")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["collection"][0]["id"], str(self.entry_id))
        self.assertNotIn("_id", response.json()["collection"][0])

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
        with patch("backend.routes.db") as database, patch("backend.routes.os.path.exists", return_value=True):
            database.__getitem__.return_value.find_one.return_value = card
            self.db.insert_one.return_value = SimpleNamespace(inserted_id=self.entry_id)
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 200)
            self.db.insert_one.reset_mock()
            for invalid in ("INVENTED-001", "CT13-FR003"):
                self.assertEqual(self.client.post("/collection/add", json=payload | {"set_code": invalid}).status_code, 422)
            database.__getitem__.return_value.find_one.return_value = None
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 422)
            database.__getitem__.return_value.find_one.return_value = {"id": card["id"]}
            self.assertEqual(self.client.post("/collection/add", json=payload).status_code, 422)
            self.db.insert_one.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
