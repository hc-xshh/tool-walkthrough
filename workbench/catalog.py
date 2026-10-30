"""Read-only product catalog.

The catalog is deliberately data, not UI state: one JSON file per vendor /
product family under `catalog/`. Adding a family means adding a file and
shipping it; the browser only displays what this loader returns. Users do not
edit families or products.

Schema (one file per family)::

    {
      "id": "qoder-cn",
      "name": "Qoder CN",
      "vendor": "Alibaba Cloud",
      "positioning": "...",
      "aliases": ["Lingma"],
      "category": ["ai-ide"],
      "homepage": "https://...",
      "docs": "https://...",
      "sources": [{"url": "...", "title": "...", "verified_at": "2026-10-30"}],
      "products": [
        {"id": "qoder-ide", "name": "Qoder CN IDE", "form": "ide",
         "surfaces": [{"id": "gui", "label": "IDE GUI", "kind": "gui",
                       "app_id": "qoder", "driver_id": "drive_qoder.py"}]}
      ]
    }

`app_id` and `driver_id` are optional references into `workbench/apps.py` and
`code-eval/drivers.json`; the catalog itself never contains executable paths,
ports, keys, or user data.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "catalog"
FORMS = {"ide", "cli", "work", "plugin", "cloud", "desktop", "agent", "web"}
SURFACE_KINDS = {"gui", "cli", "plugin", "cloud", "desktop", "agent", "web"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def catalog_dir() -> Path:
    override = os.environ.get("WT_CATALOG")
    return Path(override).expanduser() if override else DEFAULT_DIR


def _text(value) -> str:
    return str(value or "").strip()


def _family(path: Path, raw: dict) -> dict:
    fid = _text(raw.get("id"))
    if not SLUG.fullmatch(fid):
        raise ValueError(f"{path.name}: family id must be a lowercase slug")
    name = _text(raw.get("name"))
    vendor = _text(raw.get("vendor"))
    if not name or not vendor:
        raise ValueError(f"{path.name}: name and vendor are required")
    products = raw.get("products")
    if not isinstance(products, list):
        raise ValueError(f"{path.name}: products must be a list")
    seen_products: set[str] = set()
    cleaned_products = []
    for product in products:
        if not isinstance(product, dict):
            raise ValueError(f"{path.name}: product must be an object")
        pid = _text(product.get("id"))
        pname = _text(product.get("name"))
        form = _text(product.get("form"))
        if not SLUG.fullmatch(pid) or not pname:
            raise ValueError(f"{path.name}: product id/name is required")
        if pid in seen_products:
            raise ValueError(f"{path.name}: duplicate product id {pid}")
        seen_products.add(pid)
        if form not in FORMS:
            raise ValueError(f"{path.name}: unknown product form {form!r}")
        surfaces = product.get("surfaces") or []
        if not isinstance(surfaces, list):
            raise ValueError(f"{path.name}: surfaces must be a list")
        seen_surfaces: set[str] = set()
        cleaned_surfaces = []
        for surface in surfaces:
            if not isinstance(surface, dict):
                raise ValueError(f"{path.name}: surface must be an object")
            sid = _text(surface.get("id"))
            kind = _text(surface.get("kind"))
            if not SLUG.fullmatch(sid):
                raise ValueError(f"{path.name}: surface id is required")
            if sid in seen_surfaces:
                raise ValueError(f"{path.name}: duplicate surface id {sid}")
            seen_surfaces.add(sid)
            if kind not in SURFACE_KINDS:
                raise ValueError(f"{path.name}: unknown surface kind {kind!r}")
            cleaned_surfaces.append({
                "id": sid,
                "label": _text(surface.get("label")) or sid,
                "kind": kind,
                "app_id": _text(surface.get("app_id")) or None,
                "driver_id": _text(surface.get("driver_id")) or None,
            })
        cleaned_products.append({
            "id": pid,
            "name": pname,
            "form": form,
            "positioning": _text(product.get("positioning")),
            "surfaces": cleaned_surfaces,
        })
    sources = []
    for source in raw.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = _text(source.get("url"))
        if not url.startswith(("http://", "https://")):
            continue
        sources.append({
            "url": url,
            "title": _text(source.get("title")) or url,
            "verified_at": _text(source.get("verified_at")),
        })
    return {
        "id": fid,
        "name": name,
        "vendor": vendor,
        "positioning": _text(raw.get("positioning")),
        "aliases": [a for a in (_text(x) for x in raw.get("aliases") or []) if a],
        "category": [c for c in (_text(x) for x in raw.get("category") or []) if c],
        "homepage": _text(raw.get("homepage")),
        "docs": _text(raw.get("docs")),
        "sources": sources,
        "products": cleaned_products,
    }


def load() -> dict:
    """Return all valid families plus per-file errors.

    A broken file must not take the workbench down: the rest of the catalog
    still renders, and the bad file is reported so the UI can show it.
    """
    directory = catalog_dir()
    families: list[dict] = []
    errors: list[dict] = []
    seen: set[str] = set()
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("root must be an object")
            family = _family(path, raw)
            if family["id"] in seen:
                raise ValueError(f"duplicate family id {family['id']}")
            seen.add(family["id"])
            families.append(family)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"file": path.name, "error": str(exc)})
    families.sort(key=lambda item: item["name"].lower())
    return {"families": families, "errors": errors, "path": str(directory)}
