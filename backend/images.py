"""Cache persistant des images ; téléchargements sérialisés et espacés."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
import time

import httpx
from fastapi import HTTPException

IMAGE_DIR = Path(os.getenv("IMAGE_DIR", "images"))
_download_lock = Lock()
_last_download = 0.0
_failures = {}


def is_image_downloaded(image_id: int | None) -> bool:
    if image_id is None:
        return False
    path = IMAGE_DIR / f"{image_id}.jpg"
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def cached_image(image_id: int) -> Path:
    global _last_download
    if image_id <= 0:
        raise HTTPException(status_code=404, detail="Image inconnue.")
    path = IMAGE_DIR / f"{image_id}.jpg"
    # Un seul téléchargement à la fois, même lors de consultations simultanées.
    with _download_lock:
        if path.is_file() and path.stat().st_size > 0:
            return path
        if time.monotonic() < _failures.get(image_id, 0):
            raise HTTPException(status_code=503, detail="Image temporairement indisponible. Réessayez dans une minute.")
        time.sleep(max(0, 0.25 - (time.monotonic() - _last_download)))
        temporary_path = None
        try:
            _last_download = time.monotonic()
            response = httpx.get(
                f"https://images.ygoprodeck.com/images/cards/{image_id}.jpg",
                timeout=15, follow_redirects=False,
            )
            response.raise_for_status()
            if not response.content.startswith(b"\xff\xd8\xff") or not response.content.endswith(b"\xff\xd9"):
                raise ValueError("Réponse JPEG invalide ou incomplète")
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            # Le fichier final n'apparaît qu'une fois l'écriture terminée.
            with NamedTemporaryFile(dir=IMAGE_DIR, suffix=".tmp", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(response.content)
            os.replace(temporary_path, path)
            _failures.pop(image_id, None)
        except (httpx.HTTPError, ValueError, OSError) as error:
            _failures[image_id] = time.monotonic() + 60
            raise HTTPException(status_code=503, detail="Impossible de préparer l'image locale.") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return path
