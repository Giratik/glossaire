# Utilisation d'une image Python légère
FROM python:3.14-slim

# Définition du répertoire de travail dans le conteneur
WORKDIR /app

# Copie du fichier de dépendances et installation
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code source
COPY main.py .

# Exposition du port utilisé par FastAPI
EXPOSE 8000

# Commande de lancement avec rechargement automatique (pratique pour le développement)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]