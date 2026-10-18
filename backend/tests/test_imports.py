from pathlib import Path
import unittest
from unittest.mock import patch

from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo.errors import AutoReconnect

from backend.imports import parse_line
from backend.main import app


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.card = {"id": 123, "name": "Cyber Dragon Infinity", "name_fr": "Cyber Dragon Infini",
                     "card_sets": [{"set_code": "MAGO-EN033"}]}
        mocked = patch("backend.imports.db")
        self.database = mocked.start()
        self.addCleanup(mocked.stop)
        self.database["catalog"].find.return_value = [self.card]
        self.text = "2 Cyber Dragon Infinity (Alternate Art) [MAGO] MAGO-EN033"

    def test_parser_accepts_source_file_and_comma_format(self):
        source = Path(__file__).resolve().parents[2] / "dummy" / "Collection_extract.txt"
        parsed = [parse_line(line) for line in source.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        self.assertEqual(sum(row[0] for row in parsed), 624)
        self.assertEqual(parse_line('{[2], [Nibiru, the Primal Being], [CT16], [TN19-EN013]}'),
                         (2, "Nibiru, the Primal Being", "CT16", "TN19-EN013"))
        self.assertEqual(parse_line('2, "Nibiru, the Primal Being", CT16, TN19-EN013')[1], "Nibiru, the Primal Being")
        for line in ("0 Test [EXT] EXT-001", "bad line"):
            with self.assertRaises(ValueError):
                parse_line(line)

    def test_preview_uses_french_name_base_id_and_never_writes(self):
        with patch("backend.routes.collection_db") as collection, patch("backend.images.httpx.get") as download:
            response = self.client.post("/collection/import/preview", json={"text": self.text})
            self.assertEqual(response.status_code, 200)
            item = response.json()["entries"][0]["item"]
            self.assertEqual((item["card_name"], item["language"], item["image_id"], item["condition"]),
                             ("Cyber Dragon Infini", "FR", 123, "Non renseigné"))
            collection.find_one_and_update.assert_not_called()
            download.assert_not_called()

    def test_confirm_merges_quantity_even_without_catalog_images(self):
        with patch("backend.routes.collection_db") as collection, patch("backend.images.httpx.get") as download:
            collection.find_one_and_update.return_value = {"_id": ObjectId(), "quantity": 5}
            result = self.client.post("/collection/import/confirm", json={"text": self.text + "\n" + self.text}).json()
            self.assertTrue(result["completed"])
            self.assertEqual(result["total_quantity"], 4)
            self.assertEqual(collection.find_one_and_update.call_count, 2)
            identity, update = collection.find_one_and_update.call_args.args
            self.assertEqual(identity["image_id"], {"$in": [None, 123]})
            self.assertEqual(update["$inc"], {"quantity": 2})
            self.assertEqual(update["$setOnInsert"]["card_name"], "Cyber Dragon Infini")
            download.assert_not_called()

    def test_invalid_line_blocks_entire_import(self):
        with patch("backend.routes.collection_db") as collection:
            for line in ("bad line", "1 Unknown [MAGO] MAGO-EN033", "1 Cyber Dragon Infinity [X] X-001"):
                response = self.client.post("/collection/import/confirm", json={"text": self.text + "\n" + line})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["errors"][0]["line"], 2)
            collection.find_one_and_update.assert_not_called()
            self.card.pop("name_fr")
            self.assertTrue(self.client.post("/collection/import/preview", json={"text": self.text}).json()["errors"])

    def test_partial_database_failure_is_reported(self):
        with patch("backend.routes.collection_db") as collection:
            collection.find_one_and_update.side_effect = [{"_id": ObjectId(), "quantity": 2}, AutoReconnect("lost")]
            result = self.client.post("/collection/import/confirm", json={"text": self.text + "\n" + self.text}).json()
            self.assertFalse(result["completed"])
            self.assertEqual(result["failed_line"], 2)
            self.assertEqual(len(result["imported_lines"]), 1)

    def test_rarity_annotations_match_the_specific_edition(self):
        self.database["catalog"].find.return_value = [{
            "id": 13839120, "name": "Yellow Gadget", "name_fr": "Gadget Jaune",
            "card_sets": [{"set_code": "MP24-EN013", "set_rarity": "Quarter Century Secret Rare"},
                          {"set_code": "OTHER-001", "set_rarity": "Common"}],
        }]
        for name in ("Yellow Gadget", "Yellow Gadget (Quarter Century Secret Rare)",
                     "Yellow Gadget (Alternate Art) (Quarter Century Secret Rare)"):
            data = self.client.post("/collection/import/preview", json={"text": f"1 {name} [MP24] MP24-EN013"}).json()
            self.assertEqual(data["errors"], [])
            self.assertEqual(data["entries"][0]["item"]["card_name"], "Gadget Jaune")
        for name in ("Yellow Gadget (Common)", "Yellow Gadget (Unknown)", "Other Gadget (Quarter Century Secret Rare)"):
            data = self.client.post("/collection/import/preview", json={"text": f"1 {name} [MP24] MP24-EN013"}).json()
            self.assertTrue(data["errors"])

    def test_official_parentheses_in_card_name_are_preserved(self):
        self.database["catalog"].find.return_value = [{
            "id": 999, "name": "Official (Name)", "name_fr": "Nom officiel",
            "card_sets": [{"set_code": "TEST-001", "set_rarity": "Rare"}],
        }]
        data = self.client.post("/collection/import/preview", json={"text": "1 Official (Name) (Rare) [TEST] TEST-001"}).json()
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["entries"][0]["item"]["card_id"], 999)

    def test_import_saves_annotated_rarity_without_guessing_ambiguous_rarity(self):
        self.card["card_sets"] = [{"set_code": "MAGO-EN033", "set_rarity": "Rare"},
                                  {"set_code": "MAGO-EN033", "set_rarity": "Ultra Rare"}]
        for suffix, expected in [(" (Ultra Rare)", "Ultra Rare"), ("", None)]:
            data = self.client.post("/collection/import/preview", json={
                "text": f"1 Cyber Dragon Infinity{suffix} [MAGO] MAGO-EN033"}).json()
            self.assertEqual(data["errors"], [])
            self.assertEqual(data["entries"][0]["item"]["rarity"], expected)

    def test_manual_correction_replaces_invalid_line_and_is_used_on_confirm(self):
        self.card["card_sets"][0]["set_rarity"] = "Rare"
        payload = {"text": "a completely invalid export line", "corrections": {
            "1": {"card_id": 123, "quantity": 3, "set_code": "MAGO-EN033", "rarity": "Rare"}}}
        result = self.client.post("/collection/import/preview", json=payload).json()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["entries"][0]["item"]["card_name"], "Cyber Dragon Infini")
        self.assertEqual(result["total_quantity"], 3)
        with patch("backend.routes.collection_db") as collection, patch("backend.images.httpx.get") as download:
            collection.find_one_and_update.return_value = {"_id": ObjectId(), "quantity": 3}
            result = self.client.post("/collection/import/confirm", json=payload).json()
            self.assertTrue(result["completed"])
            self.assertEqual(collection.find_one_and_update.call_args.args[1]["$inc"], {"quantity": 3})
            self.assertEqual(collection.find_one_and_update.call_args.args[0]["rarity"], "Rare")
            download.assert_not_called()

    def test_corrections_cannot_bypass_catalog_validation(self):
        correction = {"card_id": 123, "quantity": 2, "set_code": "MAGO-EN033"}
        for changes in ({"card_id": 999}, {"set_code": "INVALID-001"}, {"rarity": "Unknown"}):
            payload = {"text": self.text, "corrections": {"1": correction | changes}}
            result = self.client.post("/collection/import/preview", json=payload).json()
            self.assertTrue(result["errors"])
            self.assertEqual(self.client.post("/collection/import/confirm", json=payload).status_code, 422)
        self.assertEqual(self.client.post("/collection/import/preview", json={"text": self.text,
            "corrections": {"2": correction}}).status_code, 422)

    def test_correction_search_by_english_french_code_and_id(self):
        for query in ("cyber dragon", "infini", "MAGO-EN033", "123"):
            result = self.client.get("/collection/import/candidates", params={"q": query}).json()
            self.assertEqual(result["cards"][0]["id"], 123)
        self.assertEqual(self.client.get("/collection/import/candidates", params={"q": "notfound"}).json()["total"], 0)
