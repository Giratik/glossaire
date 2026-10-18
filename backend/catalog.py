"""Consultation du catalogue local des sets et de leurs cartes."""

from fastapi import APIRouter, Query

from .database import db
from .search import normalized

router = APIRouter(prefix="/catalog", tags=["Catalogue"])


@router.get("/archetypes")
def list_archetypes(q: str = "", order: str = Query(default="asc", pattern="^(asc|desc)$")):
    counts = {}
    for card in db["catalog"].find({}, {"archetype": 1, "_id": 0}):
        name = card.get("archetype")
        if name and name.strip():
            counts[name] = counts.get(name, 0) + 1
    names = sorted((name for name in counts if normalized(q) in normalized(name)),
                   key=normalized, reverse=order == "desc")
    return {"archetypes": [{"name": name, "card_count": counts[name]} for name in names], "total": len(names)}


@router.get("/archetypes/cards")
def list_archetype_cards(archetype: str = Query(min_length=1),
                         lang: str = Query(default="fr", pattern="^(fr|en)$"),
                         order: str = Query(default="asc", pattern="^(asc|desc)$"),
                         page: int = Query(default=1, ge=1), page_size: int = Query(default=30, ge=1, le=100)):
    cards = []
    for document in db["catalog"].find({"archetype": archetype}, {"_id": 0}):
        card = dict(document)
        if lang == "fr":
            card["name"] = card.get("name_fr") or card.get("name")
            card["desc"] = card.get("desc_fr") or card.get("desc")
        cards.append(card)
    cards.sort(key=lambda c: (normalized(c["name"]), c["id"]), reverse=order == "desc")
    return {"cards": cards[(page - 1) * page_size:page * page_size], "total": len(cards),
            "page": page, "page_size": page_size}


@router.get("/sets")
def list_sets(q: str = "", sort: str = Query(default="name_asc", pattern="^(name_asc|name_desc|date_asc|date_desc)$")):
    metadata = db["metadata"].find_one({"_id": "card_sets"}) or {}
    sets = {s["set_name"]: dict(s) for s in metadata.get("sets", [])}
    # Les catalogues synchronisés avant cette fonctionnalité restent consultables.
    for card in db["catalog"].find({}, {"card_sets": 1, "_id": 0}):
        for edition in card.get("card_sets", []):
            name = edition.get("set_name")
            if name and name not in sets:
                sets[name] = {"set_name": name, "tcg_date": None}
    result = [s for s in sets.values() if normalized(q) in normalized(s["set_name"]) or normalized(q) in normalized(s.get("set_code", ""))]
    reverse = sort.endswith("desc")
    if sort.startswith("date"):
        dated = sorted((s for s in result if s.get("tcg_date")), key=lambda s: (s["tcg_date"], normalized(s["set_name"])), reverse=reverse)
        undated = sorted((s for s in result if not s.get("tcg_date")), key=lambda s: normalized(s["set_name"]))
        result = dated + undated
    else:
        result.sort(key=lambda s: normalized(s["set_name"]), reverse=reverse)
    return {"sets": result, "total": len(result), "dates_available": bool(metadata)}


@router.get("/cards")
def list_set_cards(set_name: str = Query(min_length=1), lang: str = Query(default="fr", pattern="^(fr|en)$"),
                   order: str = Query(default="name_asc", pattern="^(name_asc|name_desc|code)$"),
                   page: int = Query(default=1, ge=1), page_size: int = Query(default=30, ge=1, le=100)):
    cards = []
    for document in db["catalog"].find({"card_sets.set_name": set_name}, {"_id": 0}):
        card = dict(document)
        editions = [s for s in card.get("card_sets", []) if s.get("set_name") == set_name]
        card["set_codes"] = sorted({s["set_code"] for s in editions if s.get("set_code")})
        card["set_rarities"] = sorted({s["set_rarity"] for s in editions if s.get("set_rarity")})
        if lang == "fr":
            card["name"] = card.get("name_fr") or card.get("name")
            card["desc"] = card.get("desc_fr") or card.get("desc")
        cards.append(card)
    if order == "code":
        cards.sort(key=lambda c: (c["set_codes"], c["id"]))
    else:
        cards.sort(key=lambda c: (normalized(c["name"]), c["id"]), reverse=order == "name_desc")
    return {"cards": cards[(page - 1) * page_size:page * page_size], "total": len(cards), "page": page, "page_size": page_size}
