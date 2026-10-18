"""Recherche stricte par nom, archétype et références dans les descriptions."""

import re
import unicodedata


def search_tokens(text):
    normalized = unicodedata.normalize("NFKD", text.casefold()).replace("œ", "oe")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def normalized(text):
    return " ".join(search_tokens(text))


def localized(card, field, lang):
    return (card.get(f"{field}_fr") or card.get(field, "")) if lang == "fr" else card.get(field, "")


def resolve_archetypes(cards, tokens):
    """Un nom français n'est un alias que si son nom anglais est un archétype.

    Appartenir à un archétype ne suffit pas : Cyber Dragon Nova ne doit pas
    déclencher la recherche de tout l'archétype Cyber Dragon.
    """
    query = " ".join(tokens)
    archetypes = {normalized(c["archetype"]) for c in cards if c.get("archetype")}
    matches = {query} & archetypes
    for card in cards:
        if query in {normalized(card.get("name", "")), normalized(card.get("name_fr", ""))}:
            english_name = normalized(card.get("name", ""))
            if english_name in archetypes:
                matches.add(english_name)
    return matches


def contains_phrase(text, query):
    return f" {query} " in f" {normalized(text)} "


def relevance(card, tokens, lang, archetypes=()):
    name = localized(card, "name", lang)
    query = " ".join(tokens)
    title = normalized(name)
    if title == query:
        tier = 0
    elif normalized(card.get("archetype", "")) in archetypes:
        tier = 1
    elif contains_phrase(localized(card, "desc", lang), query):
        tier = 2
    elif contains_phrase(name, query):
        tier = 3
    else:
        return None
    return (tier, title, card["id"])
