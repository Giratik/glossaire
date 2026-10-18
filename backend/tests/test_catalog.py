import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.main import app


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        mocked = patch("backend.catalog.db")
        self.database = mocked.start()
        self.addCleanup(mocked.stop)
        self.metadata = self.database["metadata"]
        self.metadata.find_one.return_value = {"sets": [
            {"set_name": "Alpha", "set_code": "A", "tcg_date": "2020-01-01"},
            {"set_name": "Beta", "set_code": "B", "tcg_date": "2024-01-01"},
            {"set_name": "Undated"},
        ]}
        self.database["catalog"].find.return_value = []

    def test_sorts_and_filters(self):
        for sort, expected in [("name_asc", ["Alpha", "Beta", "Undated"]),
                               ("name_desc", ["Undated", "Beta", "Alpha"]),
                               ("date_desc", ["Beta", "Alpha", "Undated"]),
                               ("date_asc", ["Alpha", "Beta", "Undated"])]:
            response = self.client.get("/catalog/sets", params={"sort": sort})
            self.assertEqual([s["set_name"] for s in response.json()["sets"]], expected)
        result = self.client.get("/catalog/sets", params={"q": "béta"}).json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(self.client.get("/catalog/sets", params={"sort": "invalid"}).status_code, 422)

    def test_fallback_for_old_catalog(self):
        self.metadata.find_one.return_value = None
        self.database["catalog"].find.return_value = [{"card_sets": [{"set_name": "Legacy"}]}]
        result = self.client.get("/catalog/sets").json()
        self.assertFalse(result["dates_available"])
        self.assertEqual(result["sets"], [{"set_name": "Legacy", "tcg_date": None}])

    def test_cards_only_show_selected_set_codes_and_paginate(self):
        self.database["catalog"].find.return_value = [
            {"id": i, "name": f"Card {i:02}", "name_fr": f"Carte {i:02}", "card_sets": [
                {"set_name": "Alpha", "set_code": f"A-{i:02}", "set_rarity": "Rare"},
                {"set_name": "Other", "set_code": "OTHER-01", "set_rarity": "Common"},
            ]} for i in range(35)
        ]
        result = self.client.get("/catalog/cards", params={"set_name": "Alpha", "page": 2}).json()
        self.assertEqual(result["total"], 35)
        self.assertEqual(len(result["cards"]), 5)
        self.assertEqual(result["cards"][0]["name"], "Carte 30")
        self.assertEqual(result["cards"][0]["set_codes"], ["A-30"])
        self.database["catalog"].find.assert_called_with({"card_sets.set_name": "Alpha"}, {"_id": 0})
