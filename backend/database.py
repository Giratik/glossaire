"""Connexion MongoDB et accès aux collections de l'application."""

import os

from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://ygo_mongo:27017/")
client = MongoClient(MONGO_URL)
db = client["ygo_database"]
collection_db = db["my_cards"]
