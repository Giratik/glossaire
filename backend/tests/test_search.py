import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.search import relevance, search_tokens, resolve_archetypes


class SearchTests(unittest.TestCase):
    def test_exact_reference_and_title_order(self):
        cards = [
            {"id": 1, "name": "Cyber Dragon Nova"},
            {"id": 2, "name": "Cyber Dragon Infinity", "desc": 'Use "Cyber Dragon Nova" as material.'},
            {"id": 3, "name": "Cyber Dragon Nova Variant"},
            {"id": 4, "name": "Cyber Dragon"},
        ]
        tokens = search_tokens("cyber dragon nova")
        matches = [(relevance(c, tokens, "en"), c["id"]) for c in cards]
        self.assertEqual([i for score, i in sorted((s, i) for s, i in matches if s is not None)], [1, 2, 3])

    def test_no_approximations_or_reordered_words(self):
        for name in ["Cyber", "Dragon", "Dragon Cyber", "Cyberdark Dragon", "Cyber Ultimate Dragon"]:
            self.assertIsNone(relevance({"id": 1, "name": name}, search_tokens("cyber dragon"), "en"))
        self.assertIsNone(relevance({"id": 1, "name": "Dark Magician"}, search_tokens("dark mag"), "en"))
        self.assertIsNone(relevance({"id": 1, "name": "Other", "desc": "Cyber monster and Dragon monster"}, search_tokens("cyber dragon"), "en"))
        self.assertIsNotNone(relevance({"id": 1, "name": "Cyber Dragon Nova"}, search_tokens("cyber dragon"), "en"))
        self.assertEqual(search_tokens("[.*]"), [])

    def test_french_archetype_alias_and_priority(self):
        cards = [
            {"id": 1, "name": "Dark Magician", "name_fr": "Magicien Sombre", "archetype": "Dark Magician"},
            {"id": 2, "name": "Magician's Rod", "name_fr": "Bâton du Magicien", "archetype": "Dark Magician"},
            {"id": 3, "name_fr": "Soutien", "desc_fr": 'Invoquez un "Magicien Sombre".'},
            {"id": 4, "name_fr": "Magicien Sombre Alternatif"},
        ]
        tokens = search_tokens("MAGICIEN sömbre")
        archetypes = resolve_archetypes(cards, tokens)
        self.assertEqual(archetypes, {"dark magician"})
        ordered = sorted(cards, key=lambda c: relevance(c, tokens, "fr", archetypes))
        self.assertEqual([c["id"] for c in ordered], [1, 2, 3, 4])

    def test_specific_card_does_not_expand_its_archetype(self):
        cards = [{"id": 1, "name": "Cyber Dragon Nova", "archetype": "Cyber Dragon"},
                 {"id": 2, "name": "Cyber Dragon", "archetype": "Cyber Dragon"}]
        tokens = search_tokens("cyber dragon nova")
        self.assertEqual(resolve_archetypes(cards, tokens), set())
        self.assertEqual(resolve_archetypes(cards, search_tokens("cyber dragon")), {"cyber dragon"})

    def test_pagination_localization_and_no_results(self):
        client = TestClient(app)
        cards = [{"id": i, "name": f"Wizard {i}", "name_fr": f"Magicien {i}"} for i in range(35)]
        with patch("backend.routes.db") as database:
            catalog = database.__getitem__.return_value
            catalog.find.side_effect = lambda query, projection: (
                [c for c in cards if c["id"] in query["id"]["$in"]] if query else cards
            )
            first = client.get("/search", params={"q": "magicien", "page": 1}).json()
            second = client.get("/search", params={"q": "magicien", "page": 2}).json()
            self.assertEqual(first["total"], 35)
            self.assertEqual(len(first["cards"]), 30)
            self.assertEqual(len(second["cards"]), 5)
            self.assertTrue(first["cards"][0]["name"].startswith("Magicien"))
            self.assertFalse({c["id"] for c in first["cards"]} & {c["id"] for c in second["cards"]})
            empty = client.get("/search", params={"q": "introuvable"}).json()
            self.assertEqual(empty["total"], 0)
            self.assertEqual(empty["cards"], [])
            for params in ({"q": "[.*]"}, {"q": "x", "page": 0}, {"q": "x", "lang": "xx"}):
                self.assertEqual(client.get("/search", params=params).status_code, 422)
