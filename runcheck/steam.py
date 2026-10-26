"""Fetch and parse game requirements from the Steam store API."""
from __future__ import annotations
import html, re
import requests

API = "https://store.steampowered.com/api/appdetails"
SEARCH = "https://store.steampowered.com/api/storesearch/"


def search_game(name: str, cc: str = "us"):
    r = requests.get(SEARCH, params={"term": name, "l": "english", "cc": cc}, timeout=15)
    r.raise_for_status()
    return [{"id": i["id"], "name": i["name"]} for i in r.json().get("items", [])]


def fetch_requirements(app_id: int) -> dict:
    r = requests.get(API, params={"appids": app_id, "filters": "basic,pc_requirements"}, timeout=15)
    r.raise_for_status()
    entry = r.json().get(str(app_id), {})
    if not entry.get("success"):
        raise ValueError(f"Steam has no data for app {app_id}")
    data = entry["data"]
    reqs = data.get("pc_requirements")
    if not reqs or isinstance(reqs, list):     # Steam returns [] when empty
        raise ValueError(f"{data.get('name', app_id)} lists no PC requirements")
    return {
        "name": data.get("name", str(app_id)),
        "minimum": parse_requirements(reqs.get("minimum", "")),
        "recommended": parse_requirements(reqs.get("recommended", "")),
    }


_LABELS = {
    "os": r"os|operating system",
    "cpu": r"processor|cpu",
    "ram": r"memory|ram",
    "gpu": r"graphics|video card|gpu|video",
    "storage": r"storage|hard drive|hard disk|disk space|available space",
}


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>|</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).replace("\xa0", " ")


def to_gb(s: str):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(TB|GB|MB)", s, re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    unit = m.group(2).upper()
    return v * 1024 if unit == "TB" else v / 1024 if unit == "MB" else v


def parse_requirements(raw: str) -> dict:
    """Turn Steam's HTML blob into {os, cpu, ram_gb, gpu, vram_gb, storage_gb, raw_*}."""
    out = {"os": None, "cpu": None, "ram_gb": None, "gpu": None,
           "vram_gb": None, "storage_gb": None, "notes": None}
    if not raw:
        return out
    for line in _clean(raw).splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        label, value = [p.strip() for p in line.split(":", 1)]
        low = label.lower().replace("*", "").strip()
        for key, pat in _LABELS.items():
            if re.fullmatch(pat, low):
                if key == "ram":
                    out["ram_gb"] = to_gb(value)
                elif key == "storage":
                    out["storage_gb"] = to_gb(value)
                elif key == "gpu":
                    out["gpu"] = value
                    v = re.search(r"(\d+)\s*GB", value, re.I)
                    out["vram_gb"] = float(v.group(1)) if v else None
                else:
                    out[key] = value
                break
        else:
            if low in ("additional notes", "notes"):
                out["notes"] = value
    return out


def split_alternatives(text: str | None) -> list[str]:
    """'Intel Core i5-4460 or AMD FX-6300' -> ['Intel Core i5-4460', 'AMD FX-6300']"""
    if not text:
        return []
    text = re.sub(r"\(.*?\)", " ", text)               # drop parentheticals
    parts = re.split(r"\s+or\s+|\s*/\s*|\s*,\s*|\s+equivalent", text, flags=re.I)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 2]
