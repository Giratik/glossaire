from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import httpx
from pymongo import MongoClient
from pymongo import ReplaceOne
import os
from fastapi.staticfiles import StaticFiles

# Création du dossier d'images au démarrage
os.makedirs("images", exist_ok=True)

# Montage de la route statique juste après la définition de app = FastAPI(...)


app = FastAPI(title="Yu-Gi-Oh! Collection API")
app.mount("/local_images", StaticFiles(directory="images"), name="local_images")

# Récupération de l'URL MongoDB via les variables d'environnement (par défaut localhost si lancé hors Docker)
MONGO_URL = os.getenv("MONGO_URL", "mongodb://ygo_mongo:27017/")
client = MongoClient(MONGO_URL)
db = client["ygo_database"]
collection_db = db["my_cards"]

YGOPRODECK_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"

# Modèle pour VOTRE collection locale
class CollectionItem(BaseModel):
    card_id: int
    card_name: str
    set_code: str = Field(..., description="Ex: LOB-EN001")
    condition: str = Field(default="Near Mint", description="Mint, Near Mint, Played...")
    language: str = Field(default="FR")
    quantity: int = 1
    purchase_price: Optional[float] = None
    added_at: datetime = Field(default_factory=datetime.utcnow)

@app.get("/search/{card_name}", response_model=dict)
async def search_card_locally(card_name: str, lang: str = "fr"):
    """
    Recherche une carte directement dans la base MongoDB locale.
    """
    # 1. On détermine dans quelle colonne chercher selon la langue
    search_field = "name_fr" if lang == "fr" else "name"
    
    # 2. On crée une requête Regex pour MongoDB : 
    # $options: "i" rend la recherche insensible à la casse (majuscules/minuscules)
    # L'absence d'ancres (^ et $) permet de faire une recherche partielle.
    query = {search_field: {"$regex": card_name, "$options": "i"}}
    
    # 3. On interroge notre collection 'catalog' (en excluant l'ObjectId propre à Mongo)
    card = db["catalog"].find_one(query, {"_id": 0})
    
    if not card:
        raise HTTPException(status_code=404, detail="Carte non trouvée dans la base locale.")
        
    # 4. Si la recherche est en français, on écrase les champs anglais standard 
    # pour que l'interface Streamlit affiche bien les textes en français
    if lang == "fr":
        card["name"] = card.get("name_fr", card.get("name"))
        card["desc"] = card.get("desc_fr", card.get("desc"))
        
    return {"card_data": card}

@app.post("/collection/add")
async def add_to_collection(item: CollectionItem):
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

@app.get("/collection")
async def get_my_collection():
    cards = list(collection_db.find({}, {"_id": 0}))
    return {"total": len(cards), "collection": cards}




from datetime import datetime

# --- NOUVELLES ROUTES POUR LA VERSION ---

@app.get("/admin/version/remote")
async def check_remote_version():
    """Vérifie la version actuelle de la base de données YGOPRODeck."""
    async with httpx.AsyncClient() as client:
        res = await client.get("https://db.ygoprodeck.com/api/v7/checkDBVer.php")
        
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="Impossible de joindre l'API de version")
        
    # L'API renvoie un tableau contenant un seul objet
    return res.json()[0]

@app.get("/admin/version/local")
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

@app.post("/admin/sync")
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