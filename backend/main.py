"""Point d'entrée de l'API FastAPI."""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router

os.makedirs("images", exist_ok=True)

app = FastAPI(title="Yu-Gi-Oh! Collection API")
app.mount("/local_images", StaticFiles(directory="images"), name="local_images")
app.include_router(router)
