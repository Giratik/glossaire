from datetime import datetime
import os

import httpx
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReplaceOne

from .database import collection_db, db
from .search import search_tokens, relevance, resolve_archetypes

router = APIRouter()

YGOPRODECK_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"

# Modèle pour VOTRE collection locale
class CollectionItem(BaseModel):
    card_id: int
    card_name: str
    set_code: str = Field(..., description="Ex: LOB-EN001")
    condition: str = Field(default="Near Mint", description="Mint, Near Mint, Played...")
    language: str = Field(default="FR")
    quantity: int = 1
    added_at: datetime = Field(default_factory=datetime.utcnow)


class CollectionUpdate(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    set_code: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    language: str = Field(min_length=1)
    quantity: int = Field(ge=1, strict=True)


def collection_object_id(entry_id: str) -> ObjectId:
    if not ObjectId.is_valid(entry_id):
        raise HTTPException(status_code=400, detail="Identifiant d'entrée invalide.")
    return ObjectId(entry_id)


def validate_set_code(card_id: int, set_code: str):
    card = db["catalog"].find_one({"id": card_id}, {"card_sets": 1})
    if not card:
        raise HTTPException(status_code=422, detail="Carte absente du catalogue local. Synchronisez le catalogue.")
    codes = {edition["set_code"] for edition in card.get("card_sets", []) if edition.get("set_code")}
    if set_code not in codes:
        raise HTTPException(status_code=422, detail="Ce code d'édition n'est pas répertorié pour cette carte dans le catalogue local.")

@router.get("/search")
def search_cards(q: str = Query(min_length=1, max_length=200), lang: str = Query(default="fr", pattern="^(fr|en)$"),
                 page: int = Query(default=1, ge=1), page_size: int = Query(default=30, ge=1, le=100)):
    tokens = search_tokens(q)
    if not tokens:
        raise HTTPException(status_code=422, detail="Saisissez au moins un mot.")
    candidates = []
    projection = {"id": 1, "name": 1, "name_fr": 1, "desc": 1, "desc_fr": 1, "archetype": 1, "_id": 0}
    catalog = list(db["catalog"].find({}, projection))
    archetypes = resolve_archetypes(catalog, tokens)
    for card in catalog:
        score = relevance(card, tokens, lang, archetypes)
        if score is not None:
            candidates.append((score, card["id"]))
    candidates.sort(key=lambda result: result[0])
    ids = [card_id for _, card_id in candidates[(page - 1) * page_size:page * page_size]]
    documents = {card["id"]: card for card in db["catalog"].find({"id": {"$in": ids}}, {"_id": 0})} if ids else {}
    cards = []
    for card_id in ids:
        if card_id in documents:
            card = dict(documents[card_id])
            if lang == "fr":
                card["name"] = card.get("name_fr") or card.get("name")
                card["desc"] = card.get("desc_fr") or card.get("desc")
            score = relevance(documents[card_id], tokens, lang, archetypes)
            card["search_match"] = ["Nom exact", "Archétype", "Référence dans le texte", "Expression dans le titre"][score[0]]
            cards.append(card)
    return {"cards": cards, "total": len(candidates), "page": page, "page_size": page_size}


@router.get("/search/{card_name}")
def search_card_locally(card_name: str, lang: str = "fr"):
    # Compatibilité avec les anciens clients utilisant le premier résultat.
    if lang not in {"fr", "en"}:
        raise HTTPException(status_code=422, detail="Langue invalide.")
    result = search_cards(card_name, lang, 1, 30)
    if not result["cards"]:
        raise HTTPException(status_code=404, detail="Carte non trouvée dans la base locale.")
    return {"card_data": result["cards"][0], **result}

@router.post("/collection/add")
async def add_to_collection(item: CollectionItem):
    validate_set_code(item.card_id, item.set_code)
    item_dict = item.model_dump()
    
    # 1. Vérification et téléchargement de l'image
    image_path = f"images/{item.card_id}.jpg"
    if not os.path.exists(image_path):
        async with httpx.AsyncClient() as client:
            image_url = f"https://images.ygoprodeck.com/images/cards/{item.card_id}.jpg"
            img_res = await client.get(image_url)
            
            if img_res.status_code == 200:
                # Écriture du fichier binaire sur le volume Docker
                with open(image_path, "wb") as f:
                    f.write(img_res.content)
    
    # 2. Insertion en base de données
    result = collection_db.insert_one(item_dict)
    
    return {
        "message": "Carte ajoutée et image sauvegardée avec succès", 
        "inserted_id": str(result.inserted_id)
    }

@router.get("/collection")
async def get_my_collection():
    cards = []
    for document in collection_db.find({}, {"purchase_price": 0}):
        card = dict(document)
        card["id"] = str(card.pop("_id"))
        cards.append(card)
    return {"total": len(cards), "collection": cards}


@router.put("/collection/{entry_id}")
def update_collection_entry(entry_id: str, item: CollectionUpdate):
    object_id = collection_object_id(entry_id)
    existing = collection_db.find_one({"_id": object_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Entrée introuvable.")
    # Les anciennes éditions restent modifiables si leur code ne change pas.
    if item.set_code != existing.get("set_code"):
        validate_set_code(existing["card_id"], item.set_code)
    result = collection_db.update_one(
        {"_id": object_id}, {"$set": item.model_dump(), "$unset": {"purchase_price": ""}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Entrée introuvable.")
    return {"message": "Entrée modifiée."}


@router.delete("/collection/{entry_id}")
def delete_collection_entry(entry_id: str):
    result = collection_db.delete_one({"_id": collection_object_id(entry_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Entrée introuvable.")
    return {"message": "Entrée supprimée."}

# --- NOUVELLES ROUTES POUR LA VERSION ---

@router.get("/admin/version/remote")
async def check_remote_version():
    """Vérifie la version actuelle de la base de données YGOPRODeck."""
    async with httpx.AsyncClient() as client:
        res = await client.get("https://db.ygoprodeck.com/api/v7/checkDBVer.php")
        
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="Impossible de joindre l'API de version")
        
    # L'API renvoie un tableau contenant un seul objet
    return res.json()[0]

@router.get("/admin/version/local")
async def get_local_version():
    """Récupère les informations de version sauvegardées localement."""
    meta = db["metadata"].find_one({"_id": "db_info"})
    if meta:
        return {
            "database_version": meta.get("database_version"),
            "last_update": meta.get("last_update"),
            "local_sync_date": meta.get("local_sync_date")
        }
    return {"database_version": "Inconnue", "last_update": "Jamais", "local_sync_date": "Jamais"}


# --- MODIFICATION DE LA ROUTE DE SYNCHRONISATION ---
# (Remplacez votre fonction sync_database_locally existante par celle-ci)

@router.post("/admin/sync")
async def sync_database_locally():
    async with httpx.AsyncClient(timeout=60.0) as client:
        res_en = await client.get(YGOPRODECK_URL)
        res_fr = await client.get(YGOPRODECK_URL, params={"language": "fr"})
        # NOUVEAU : On récupère aussi la version pendant la synchro
        res_ver = await client.get("https://db.ygoprodeck.com/api/v7/checkDBVer.php")
        
    if res_en.status_code != 200 or res_fr.status_code != 200:
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération depuis YGOPRODeck")
        
    cards_en = res_en.json()["data"]
    cards_fr = res_fr.json()["data"]
    fr_dict = {c["id"]: c for c in cards_fr}
    bulk_ops = []
    
    for card in cards_en:
        card_id = card["id"]
        if card_id in fr_dict:
            card["name_fr"] = fr_dict[card_id]["name"]
            card["desc_fr"] = fr_dict[card_id]["desc"]
        else:
            card["name_fr"] = card["name"]
            card["desc_fr"] = card["desc"]
            
        bulk_ops.append(ReplaceOne({"id": card_id}, card, upsert=True))
        
    if bulk_ops:
        db["catalog"].bulk_write(bulk_ops)
        
    # NOUVEAU : Sauvegarde des métadonnées après la synchro
    if res_ver.status_code == 200:
        version_data = res_ver.json()[0]
        db["metadata"].update_one(
            {"_id": "db_info"},
            {"$set": {
                "database_version": version_data["database_version"],
                "last_update": version_data["last_update"],
                "local_sync_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }},
            upsert=True
        )
        
    return {"message": f"Succès : {len(bulk_ops)} cartes synchronisées en local."}
