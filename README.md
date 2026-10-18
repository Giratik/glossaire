# Collection Yu-Gi-Oh!

Application personnelle de gestion de collection : recherche dans un catalogue
local bilingue, ajout de cartes, inventaire et synchronisation avec YGOPRODeck.

## Organisation

- `frontend/` : interface Streamlit, dépendances et Dockerfile.
- `backend/` : API FastAPI, dépendances et Dockerfile.
  - `main.py` : création de l'application et montage des images statiques.
  - `database.py` : connexion MongoDB et accès aux collections.
  - `routes.py` : routes API et modèle des données de collection.
  - `images.py` : téléchargement à la demande et cache persistant des images.
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

## Import texte

L'onglet **Import texte** accepte un fichier `.txt`, avec une entrée par ligne :

```text
3 Union Hangar [MAGO] MAGO-EN103
```

Le format `quantité, nom anglais, extension, code de carte` est également accepté.
L'analyse affiche un aperçu et les erreurs avant confirmation. Toute erreur de
validation bloque l'import entier. Les noms français proviennent du catalogue
local ; les noms anglais, codes inconnus ou traductions manquantes sont signalés.
La langue est FR, l'état est Non renseigné par défaut et l'illustration utilise
l'ID principal. Aucun téléchargement d'image n'est déclenché par l'import.
L'aperçu des images dans la collection est désormais activé à la demande.

Les quantités s'ajoutent aux entrées identiques. Réimporter volontairement le même
fichier augmente à nouveau les quantités ; le bouton de confirmation reste donc
désactivé pour un fichier déjà tenté pendant la session. En cas d'erreur réseau
ou MongoDB, vérifier la collection avant toute relance : des écritures peuvent
avoir réussi. L'import ne remplace ni ne vide la collection existante.

## Catalogue et images

L'onglet **Catalogue des sets** permet de filtrer les sets par nom, code et année,
de les trier par nom ou date de sortie TCG, puis de consulter leurs cartes par
pages de 30 avec aperçu local. Les dates et la liste complète des sets sont
récupérées lors de la synchronisation complète dans Administration. Les anciens
catalogues restent consultables sans dates en attendant cette synchronisation.

L'aperçu passe par `GET /cards/{card_id}/image`. À la première consultation,
l'API télécharge l'illustration principale puis la conserve dans `images/`.
Les consultations suivantes réutilisent ce fichier, y compris après redémarrage.
Streamlit reçoit les octets depuis l'API et ne charge jamais l'URL distante.
Les fichiers déjà téléchargés sont réutilisés. Les illustrations alternatives
ne sont pas téléchargées tant qu'elles ne sont pas utilisées par l'interface.

En Docker, les images restent dans le volume `card_images` monté sur `/app/images`.
En local, `IMAGE_DIR` permet de choisir un autre dossier. Les téléchargements sont
sérialisés et espacés d'au moins 250 ms dans le processus API ; un échec entraîne
une pause d'une minute avant une nouvelle tentative pour cette image.
Un échec d'image n'empêche pas d'ajouter une carte à la collection.

Ce fonctionnement suit les consignes de stockage local de
[YGOPRODeck](https://ygoprodeck.com/api-guide/). La synchronisation du catalogue
ne télécharge pas toutes les images en masse.
