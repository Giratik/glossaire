# Collection Yu-Gi-Oh!

Application personnelle de gestion de collection : recherche dans un catalogue
local bilingue, ajout de cartes, inventaire et synchronisation avec YGOPRODeck.

## Organisation

- `frontend/` : interface Streamlit, dépendances et Dockerfile.
- `backend/` : API FastAPI, dépendances et Dockerfile.
  - `main.py` : création de l'application et montage des images statiques.
  - `database.py` : connexion MongoDB et accès aux collections.
  - `routes.py` : routes API et modèle des données de collection.
- `docker-compose.yml` : lancement de MongoDB, de l'API et de l'interface.
- `requirements.txt` : installation commune des dépendances pour le développement local.

Les deux images utilisent Python 3.14 slim. Les fichiers `.dockerignore` se trouvent
dans chaque contexte de construction.

## Lancement avec Docker

Démarrer Docker Desktop, puis exécuter à la racine du projet :

```powershell
docker compose up --build -d
```

- Interface : http://localhost:8501
- Documentation de l'API : http://localhost:8000/docs
- MongoDB : localhost:27017

Au premier lancement, ouvrir l'onglet Administration et lancer la synchronisation
complète pour remplir le catalogue avant de rechercher une carte.

```powershell
docker compose logs -f
docker compose down
```

Les volumes `mongo_data` et `card_images` conservent la base et les images entre
les démarrages. Ne pas utiliser `docker compose down -v` pour un arrêt ordinaire :
cette option supprime les volumes et leurs données.

## Développement local

Depuis la racine, avec un environnement Python 3.14 activé :

```powershell
python -m pip install -r requirements.txt
docker compose up -d ygo_mongo
$env:MONGO_URL = "mongodb://localhost:27017/"
python -m uvicorn backend.main:app --reload
```

Dans un second terminal avec le même environnement activé :

```powershell
$env:API_URL = "http://localhost:8000"
python -m streamlit run frontend/app.py
```

En Docker, l'interface utilise par défaut `http://ygo_api:8000` et l'API utilise
`mongodb://ygo_mongo:27017/`. Les images téléchargées sont enregistrées dans
`images/`, relativement au dossier de lancement de l'API.
