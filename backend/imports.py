"""Import texte depuis le catalogue local, sans téléchargement d'images."""

import csv
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from .database import db
from .routes import CollectionItem, store_collection_item
from .search import normalized

router = APIRouter(prefix="/collection/import", tags=["Import"])


class ImportCorrection(BaseModel):
    card_id: int = Field(gt=0, strict=True)
    quantity: int = Field(ge=1, le=1_000_000, strict=True)
    set_code: str = Field(min_length=1)
    rarity: str | None = Field(default=None, min_length=1)


class TextImport(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    condition: str = Field(default="Non renseigné", min_length=1, max_length=40)
    corrections: dict[int, ImportCorrection] = Field(default_factory=dict)


@router.get("/candidates")
def correction_candidates(q: str = Query(min_length=1, max_length=200)):
    query = normalized(q)
    if not query:
        raise HTTPException(status_code=422, detail="Saisissez un nom, un code ou un ID.")
    matches = []
    for card in db["catalog"].find({}, {"id": 1, "name": 1, "name_fr": 1, "card_sets": 1, "_id": 0}):
        values = [card.get("name", ""), card.get("name_fr", ""), str(card["id"])]
        values.extend(s.get("set_code", "") for s in card.get("card_sets", []))
        if any(query in normalized(value) for value in values):
            matches.append(card)
    matches.sort(key=lambda c: (query not in {normalized(c.get("name", "")), normalized(c.get("name_fr", "")), str(c["id"])}, normalized(c.get("name", "")), c["id"]))
    return {"cards": matches[:100], "total": len(matches)}


def parse_line(line):
    line = line.strip().lstrip("\ufeff").strip("{} ")
    match = re.fullmatch(r"(\d+)\s+(.+?)\s+\[([^\]]+)\]\s+(\S+)", line)
    if match:
        quantity, name, extension, code = match.groups()
    else:
        parts = next(csv.reader([line], skipinitialspace=True))
        if len(parts) < 4:
            raise ValueError("Format attendu : quantité Nom anglais [EXT] EXT-EN001, ou quatre champs séparés par des virgules.")
        quantity, name, extension, code = parts[0], ", ".join(parts[1:-2]), parts[-2], parts[-1]
        quantity, name, extension, code = [value.strip().strip("[]\"").strip() for value in (quantity, name, extension, code)]
    if not quantity.isdecimal() or not 1 <= int(quantity) <= 1_000_000 or not name or not extension or not code:
        raise ValueError("Quantité ou champ invalide.")
    return int(quantity), name, extension, code


def resolve_import_card(name, code, by_name):
    # Essayer le nom officiel complet avant de retirer une annotation : certaines
    # cartes ont réellement des parenthèses dans leur nom.
    candidates = by_name.get(normalized(name), [])
    annotations = []
    while not candidates:
        suffix = re.fullmatch(r"(.+?)\s*\(([^()]*)\)\s*", name)
        if not suffix:
            raise ValueError("Nom anglais introuvable ou annotation non reconnue dans le catalogue local.")
        name, annotation = suffix.groups()
        annotations.append(normalized(annotation))
        candidates = by_name.get(normalized(name), [])
    matches = []
    for card in candidates:
        editions = [edition for edition in card.get("card_sets", []) if edition.get("set_code") == code]
        if not editions:
            continue
        allowed = {normalized("Alternate Art"), normalized("Alternative Art")}
        allowed.update(normalized(edition["set_rarity"]) for edition in editions if edition.get("set_rarity"))
        if all(annotation in allowed for annotation in annotations):
            matches.append(card)
    if len(matches) != 1:
        raise ValueError("Nom, code d'édition ou annotation de rareté incompatible ou ambigu dans le catalogue local.")
    card = matches[0]
    rarities = {edition["set_rarity"] for edition in card.get("card_sets", [])
                if edition.get("set_code") == code and edition.get("set_rarity")}
    annotated = [rarity for rarity in rarities if normalized(rarity) in annotations]
    if len(annotated) > 1:
        raise ValueError("Plusieurs raretés contradictoires dans le nom exporté.")
    rarity = annotated[0] if annotated else next(iter(rarities)) if len(rarities) == 1 else None
    return card, rarity


def prepare_import(payload):
    lines = [(number, line) for number, line in enumerate(payload.text.splitlines(), 1) if line.strip()]
    if not lines or len(lines) > 5000:
        raise HTTPException(status_code=422, detail="Le fichier doit contenir entre 1 et 5 000 entrées.")
    by_name = {}
    by_id = {}
    for card in db["catalog"].find({}, {"id": 1, "name": 1, "name_fr": 1, "card_sets": 1, "_id": 0}):
        by_name.setdefault(normalized(card.get("name", "")), []).append(card)
        by_id[card["id"]] = card
    if set(payload.corrections) - {number for number, _ in lines}:
        raise HTTPException(status_code=422, detail="Une correction référence une ligne absente du fichier.")
    entries, errors = [], []
    for number, line in lines:
        quantity = None
        try:
            correction = payload.corrections.get(number)
            if correction:
                quantity, code, rarity = correction.quantity, correction.set_code, correction.rarity
                card = by_id.get(correction.card_id)
                if not card:
                    raise ValueError("Carte sélectionnée absente du catalogue local.")
                editions = [s for s in card.get("card_sets", []) if s.get("set_code") == code]
                if rarity is not None and rarity not in {s.get("set_rarity") for s in editions}:
                    raise ValueError("Rareté incompatible avec l'édition sélectionnée.")
                extension = next((s.get("set_name", "") for s in editions), "")
            else:
                quantity, name, extension, code = parse_line(line)
                card, rarity = resolve_import_card(name, code, by_name)
            if not card.get("name_fr") or not card["name_fr"].strip():
                raise ValueError("Nom français absent du catalogue local.")
            if code not in {s.get("set_code") for s in card.get("card_sets", [])}:
                raise ValueError("Code d'édition absent pour cette carte dans le catalogue local.")
            item = CollectionItem(card_id=card["id"], image_id=card["id"], card_name=card["name_fr"],
                                  quantity=quantity, set_code=code, rarity=rarity, language="FR", condition=payload.condition)
            entries.append({"line": number, "extension": extension, "item": item.model_dump(mode="json")})
        except (ValueError, csv.Error) as error:
            errors.append({"line": number, "text": line, "error": str(error), "quantity": quantity})
    return {"entries": entries, "errors": errors, "total_lines": len(lines),
            "total_quantity": sum(e["item"]["quantity"] for e in entries)}


@router.post("/preview")
def preview_import(payload: TextImport):
    return prepare_import(payload)


@router.post("/confirm")
def confirm_import(payload: TextImport):
    prepared = prepare_import(payload)
    if prepared["errors"]:
        raise HTTPException(status_code=422, detail=prepared)
    imported = []
    for entry in prepared["entries"]:
        item = CollectionItem(**entry["item"])
        try:
            result = store_collection_item(item, item.card_id, item.card_id)
        except PyMongoError:
            return {"completed": False, "imported_lines": imported, "failed_line": entry["line"],
                    "message": "Import interrompu. Certaines écritures peuvent avoir réussi : vérifiez la collection avant toute relance."}
        imported.append({"line": entry["line"], "entry_id": result["inserted_id"], "quantity": item.quantity})
    return {"completed": True, "imported_lines": imported, "total_quantity": prepared["total_quantity"],
            "message": f"Import terminé : {len(imported)} ligne(s), {prepared['total_quantity']} exemplaire(s)."}
