"""
store.py — Persistencia en archivos JSON

Dos orígenes de datos, separados a propósito:

  • Catálogo ESTÁTICO (versionado en el repo, dentro de data/):
        data/products.json        ← catálogo (editable a mano)
        data/payment_info.json     ← datos de transferencia (editable a mano)

  • Datos TRANSACCIONALES de ventas (volumen persistente independiente,
    ruta = settings.TX_DATA_DIR, fuera del repo):
        {TX_DATA_DIR}/clients.json
        {TX_DATA_DIR}/engagements.json
        {TX_DATA_DIR}/payments.json

MongoDB actúa como registro de ventas aparte (ver sales_log.py); NO es la
fuente de verdad operativa. Estos JSON sí lo son.

Concurrencia
------------
Cada `JSONCollection` serializa sus escrituras con un lock a nivel de sistema
operativo (`fcntl.flock` sobre un archivo `.lock` dedicado). Esto garantiza
que las escrituras se procesen de forma secuencial incluso entre múltiples
procesos/workers de uvicorn/gunicorn, no solo entre hilos. Se combina con
escritura atómica (write a .tmp + os.replace) para que un fallo a mitad de
escritura nunca deje el JSON corrupto.
"""

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from app.core.config import settings

# Catálogo estático: data/ en la raíz del repo (dos niveles arriba de app/core/).
CATALOG_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Datos transaccionales: volumen persistente (configurable). Puede ser ruta
# relativa (dev) o absoluta (montaje del disco en producción).
TX_DATA_DIR = Path(settings.TX_DATA_DIR)


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"No serializable a JSON: {type(obj)}")


def _matches(doc: dict, filters: dict) -> bool:
    """Coincidencia por igualdad simple de todos los campos del filtro."""
    return all(doc.get(k) == v for k, v in filters.items())


def new_id() -> str:
    """ID hexadecimal de 24 chars — mismo largo que un ObjectId de Mongo."""
    return uuid.uuid4().hex[:24]


class JSONCollection:
    def __init__(self, name: str, base_dir: Path):
        self.name = name
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / f"{name}.json"
        self.lock_path = self.base_dir / f"{name}.lock"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    # ── Lock a nivel de SO (serializa escrituras entre procesos) ──
    @contextmanager
    def _flock(self):
        # Un descriptor dedicado al archivo .lock; flock exclusivo bloquea
        # hasta que cualquier otro proceso/hilo libere el lock.
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # ── IO ────────────────────────────────────────────────────────
    def _read(self) -> list:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _write(self, docs: list) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2, default=_json_default)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # escritura atómica

    # ── Lectura ───────────────────────────────────────────────────
    def find(self, filters: Optional[dict] = None, sort: Optional[tuple] = None) -> list:
        """Devuelve los documentos que coinciden. `sort=(campo, 1|-1)`."""
        docs = self._read()
        if filters:
            docs = [d for d in docs if _matches(d, filters)]
        if sort:
            key, direction = sort
            docs.sort(
                key=lambda d: (d.get(key) is None, d.get(key)),
                reverse=direction < 0,
            )
        return docs

    def find_one(self, filters: dict) -> Optional[dict]:
        for d in self.find(filters):
            return d
        return None

    # ── Escritura (siempre bajo flock) ────────────────────────────
    def insert(self, doc: dict, gen_id: bool = True) -> dict:
        with self._flock():
            docs = self._read()
            if gen_id and "id" not in doc:
                doc = {"id": new_id(), **doc}
            docs.append(doc)
            self._write(docs)
        return doc

    def insert_many(self, new_docs: list, gen_id: bool = True) -> list:
        out = []
        with self._flock():
            docs = self._read()
            for d in new_docs:
                if gen_id and "id" not in d:
                    d = {"id": new_id(), **d}
                docs.append(d)
                out.append(d)
            self._write(docs)
        return out

    def update_one(self, filters: dict, changes: dict) -> Optional[dict]:
        """Aplica `changes` (merge) al primer documento que coincida."""
        with self._flock():
            docs = self._read()
            for d in docs:
                if _matches(d, filters):
                    d.update(changes)
                    self._write(docs)
                    return d
        return None

    def upsert(self, filters: dict, changes: dict, on_insert: Optional[dict] = None) -> dict:
        """Actualiza si existe; si no, inserta combinando filtros + changes."""
        with self._flock():
            docs = self._read()
            for d in docs:
                if _matches(d, filters):
                    d.update(changes)
                    self._write(docs)
                    return d
            doc = {"id": new_id()}
            if on_insert:
                doc.update(on_insert)
            doc.update(filters)
            doc.update(changes)
            docs.append(doc)
            self._write(docs)
        return doc

    def delete_one(self, filters: dict) -> bool:
        with self._flock():
            docs = self._read()
            for i, d in enumerate(docs):
                if _matches(d, filters):
                    docs.pop(i)
                    self._write(docs)
                    return True
        return False


def load_document(name: str) -> dict:
    """Carga un archivo JSON de documento único del catálogo (p. ej. payment_info)."""
    path = CATALOG_DIR / f"{name}.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Colecciones ───────────────────────────────────────────────────
# Catálogo estático (repo):
products    = JSONCollection("products", CATALOG_DIR)
# Transaccional (volumen persistente):
clients     = JSONCollection("clients",     TX_DATA_DIR)
engagements = JSONCollection("engagements", TX_DATA_DIR)
payments    = JSONCollection("payments",    TX_DATA_DIR)
