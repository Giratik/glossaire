import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.main import app


class ArchetypeTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        mocked = patch("backend.catalog.db")
        self.database = mocked.start()
        self.addCleanup(mocked.stop)
        self.cards = [
            {"id": i, "name": f"Wizard {i:02}", "name_fr": f"Magicien {i:02}", "archetype": "Dark Magician"}
            for i in range(35)
        ] + [{"id": 100, "name": "Dragon", "archetype": "Cyber Dragon"},
             {"id": 101, "name": "Support", "desc": "Dark Magician"},
             {"id": 102, "name": "Empty", "archetype": ""}]
        self.database["catalog"].find.side_effect = lambda query, projection: (
            [c for c in self.cards if c.get("archetype") == query["archetype"]] if query else self.cards
        )

    def test_list_counts_filter_and_order(self):
        data = self.client.get("/catalog/archetypes").json()
        self.assertEqual(data["archetypes"], [{"name": "Cyber Dragon", "card_count": 1}, {"name": "Dark Magician", "card_count": 35}])
        descending = self.client.get("/catalog/archetypes", params={"order": "desc"}).json()
        self.assertEqual(descending["archetypes"][0]["name"], "Dark Magician")
        filtered = self.client.get("/catalog/archetypes", params={"q": "dárk"}).json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(self.client.get("/catalog/archetypes", params={"q": "unknown"}).json()["total"], 0)

    def test_exact_membership_pagination_and_french_names(self):
        data = self.client.get("/catalog/archetypes/cards", params={"archetype": "Dark Magician", "page": 2}).json()
        self.assertEqual(data["total"], 35)
        self.assertEqual(len(data["cards"]), 5)
        self.assertEqual(data["cards"][0]["name"], "Magicien 30")
        english = self.client.get("/catalog/archetypes/cards", params={"archetype": "Dark Magician", "lang": "en", "order": "desc"}).json()
        self.assertEqual(english["cards"][0]["name"], "Wizard 34")
        self.assertEqual(self.client.get("/catalog/archetypes/cards", params={"archetype": "unknown"}).json()["cards"], [])

    def test_invalid_parameters(self):
        for params in ({"archetype": ""}, {"archetype": "X", "page": 0}, {"archetype": "X", "lang": "xx"}):
            self.assertEqual(self.client.get("/catalog/archetypes/cards", params=params).status_code, 422)
