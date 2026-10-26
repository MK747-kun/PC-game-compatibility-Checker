"""Match hardware names to performance scores."""
from __future__ import annotations
import csv, re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"

_JUNK = [
    r"\b\d+(st|nd|rd|th) gen\b", r"\b(dual|tri|quad|hexa|six|octa|eight|ten|twelve)-core\b",
    r"\(r\)|\(tm\)|®|™", r"\bnvidia\b", r"\bgeforce\b", r"\bamd\b", r"\bintel\b",
    r"\bradeon\b(?!\s+(vega|610m|660m|680m|780m))", r"\bseries\b", r"\bgraphics\b(?!\s*\d)",
    r"\bcpu\b", r"\bprocessor\b", r"@.*$", r"\d+(\.\d+)?\s*ghz", r"\d+-core",
    r"\bwith\b.*$", r"\bor (better|higher|equivalent|faster)\b", r"\bequivalent\b",
    r"\bor\b.*$", r"\b(laptop|mobile|max-q)\b", r"\b\d{3,5}\s*mb\b",
]


def normalize(name: str) -> str:
    s = name.lower()
    for pat in _JUNK:
        s = re.sub(pat, " ", s)
    s = re.sub(r"\bgtx(\d)", r"gtx \1", s)
    s = re.sub(r"\brtx(\d)", r"rtx \1", s)
    s = re.sub(r"(\d)\s+gb\b", r"\1gb", s)
    s = re.sub(r"[^a-z0-9\- ]", " ", s)
    s = re.sub(r"\bradeon rx\b", "rx", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(core i\d)\s+(\d{4,5}[a-z]*)", r"\1-\2", s)   # "i5 4460" -> "i5-4460"
    s = re.sub(r"\b(i\d)-?(\d{4,5})", r"core \1-\2", s) if not s.startswith("core") else s
    s = s.replace("core core", "core")
    return s


@lru_cache(maxsize=None)
def _load(kind: str) -> dict:
    table = {}
    with open(DATA / f"{kind}.csv", newline="") as f:
        rows = (r for r in f if not r.startswith("#"))
        for row in csv.DictReader(rows):
            table[normalize(row["name"])] = float(row["score"])
    return table


def lookup(kind: str, name: str):
    """Return (score, matched_name) or (None, None). kind is 'gpus' or 'cpus'."""
    score, matched = _lookup(kind, name)
    if score is not None and re.search(r"laptop|mobile|max-q", name, re.I):
        score *= 0.8      # laptop parts run at lower power limits than desktop ones
    return score, matched


def _lookup(kind: str, name: str):
    table = _load(kind)
    q = normalize(name)
    if q in table:
        return table[q], q
    # query is a longer string than the entry: "gtx 1060 6gb 6144mb" vs "gtx 1060 6gb"
    longer = [k for k in table if q.startswith(k + " ") or q == k]
    if longer:
        k = max(longer, key=len)
        return table[k], k
    # query is a shorter string than entries: "gtx 1060" -> pick weakest variant (conservative)
    shorter = [k for k in table if k.startswith(q + " ")]
    if shorter:
        k = min(shorter, key=lambda x: table[x])
        return table[k], k
    return None, None
