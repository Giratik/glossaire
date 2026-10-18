"""Point d'entrée de l'API FastAPI."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router
from .images import IMAGE_DIR
from .catalog import router as catalog_router
from .imports import router as import_router

IMAGE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Yu-Gi-Oh! Collection API")
app.mount("/local_images", StaticFiles(directory=IMAGE_DIR), name="local_images")
app.include_router(router)
app.include_router(catalog_router)
app.include_router(import_router)
