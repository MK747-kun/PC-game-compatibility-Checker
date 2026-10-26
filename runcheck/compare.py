"""Compare detected specs against a game's requirements and produce a verdict."""
from __future__ import annotations
from dataclasses import dataclass, field

from .scores import lookup
from .steam import split_alternatives

# Verdict levels, worst to best
BELOW, BORDERLINE, MINIMUM, RECOMMENDED, EXCEEDS = range(5)
LABELS = {
    BELOW: "Will not run well (below minimum)",
    BORDERLINE: "Borderline (just under minimum, expect problems)",
    MINIMUM: "Runs at minimum (low settings, around 30 fps)",
    RECOMMENDED: "Meets recommended (medium-high settings, around 60 fps)",
    EXCEEDS: "Comfortably exceeds recommended (high settings)",
}


@dataclass
class Part:
    name: str                 # "CPU", "GPU", "RAM", "VRAM", "Disk"
    yours: str
    min_req: str | None
    rec_req: str | None
    vs_min: float | None      # your value / minimum requirement
    vs_rec: float | None
    level: int | None         # None = couldn't compare
    note: str = ""


@dataclass
class Result:
    game: str
    verdict: int | None
    parts: list = field(default_factory=list)
    bottleneck: Part | None = None
    advice: list = field(default_factory=list)
    unknown: list = field(default_factory=list)
    perf_verdict: int | None = None     # verdict ignoring disk space (how fast it will run)


def _req_score(kind: str, text: str | None):
    """Lowest score across 'A or B' alternatives (either one satisfies the requirement)."""
    scores = []
    for alt in split_alternatives(text):
        s, _ = lookup(kind, alt)
        if s is not None:
            scores.append(s)
    return min(scores) if scores else None


def _level(vs_min, vs_rec):
    if vs_min is None:
        return None
    if vs_min < 0.85:
        return BELOW
    if vs_min < 1.0:
        return BORDERLINE
    if vs_rec is None:
        return MINIMUM if vs_min < 1.5 else RECOMMENDED
    if vs_rec < 1.0:
        return MINIMUM
    return RECOMMENDED if vs_rec < 1.5 else EXCEEDS


_RAM_SIZES = [2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256]


def nominal_ram(gb: float) -> float:
    """Windows reports usable RAM (a '16 GB' PC shows ~15.4). Snap to the installed size."""
    for size in _RAM_SIZES:
        if size >= gb and gb / size >= 0.85:
            return float(size)
    return gb


def _numeric_part(name, yours, unit, min_v, rec_v):
    if yours is None or min_v is None:
        return Part(name, f"{yours} {unit}" if yours else "unknown", None, None, None, None, None,
                    "not listed by the game" if min_v is None else "couldn't read your value")
    vs_min = yours / min_v
    vs_rec = yours / rec_v if rec_v else None
    return Part(name, f"{yours:g} {unit}", f"{min_v:g} {unit}",
                f"{rec_v:g} {unit}" if rec_v else None, vs_min, vs_rec, _level(vs_min, vs_rec))


def _scored_part(name, kind, your_name, req):
    mn, rc = req["minimum"], req["recommended"]
    key = "cpu" if kind == "cpus" else "gpu"
    yours, _ = lookup(kind, your_name) if your_name else (None, None)
    min_s, rec_s = _req_score(kind, mn.get(key)), _req_score(kind, rc.get(key))
    label = your_name or "unknown"
    if yours is None:
        return Part(name, label, mn.get(key), rc.get(key), None, None, None,
                    "your hardware isn't in the score table yet")
    if min_s is None and rec_s is None:
        return Part(name, label, mn.get(key), rc.get(key), None, None, None,
                    "couldn't match the game's listed hardware to the score table")
    if min_s is None:
        min_s = rec_s * 0.6          # no minimum listed: assume ~60% of recommended
    return Part(name, label, mn.get(key), rc.get(key), yours / min_s,
                yours / rec_s if rec_s else None, _level(yours / min_s, yours / rec_s if rec_s else None))


def compare(specs, req: dict) -> Result:
    mn, rc = req["minimum"], req["recommended"]
    gpu = specs.best_gpu()
    gpu_name = gpu["name"] if gpu else None
    parts = [
        _scored_part("CPU", "cpus", specs.cpu, req),
        _scored_part("GPU", "gpus", gpu_name, req),
        _numeric_part("RAM", nominal_ram(specs.ram_gb) if specs.ram_gb else None, "GB", mn.get("ram_gb"), rc.get("ram_gb")),
    ]
    vram = gpu.get("vram_gb") if gpu else None
    min_vram, rec_vram = mn.get("vram_gb"), rc.get("vram_gb")
    if min_vram or rec_vram:
        parts.append(_numeric_part("VRAM", vram, "GB", min_vram or rec_vram, rec_vram))
    disk_need = rc.get("storage_gb") or mn.get("storage_gb")
    if disk_need:
        p = _numeric_part("Disk", specs.free_disk_gb, "GB free", disk_need, None)
        p.level = BELOW if specs.free_disk_gb < disk_need else EXCEEDS   # disk only ever fails, never caps the verdict
        parts.append(p)

    known = [p for p in parts if p.level is not None]
    unknown = [p for p in parts if p.level is None]
    perf = [p for p in known if p.name != "Disk"]
    perf_v = min((p.level for p in perf), default=None)      # you're only as good as your weakest part
    core_unknown = any(p.name in ("CPU", "GPU") and p.level is None for p in parts)
    if core_unknown and perf_v is not None and perf_v > BELOW:
        perf_v = None                                       # can't promise anything without CPU and GPU
    disk = next((p for p in known if p.name == "Disk"), None)
    verdict = BELOW if (disk is not None and disk.level == BELOW) else perf_v
    res = Result(req["name"], verdict, parts, unknown=unknown, perf_verdict=perf_v)

    scored = [p for p in known if p.name != "Disk"]
    if scored:
        res.bottleneck = min(scored, key=lambda p: (p.level, p.vs_min))
    res.advice = _advice(res, specs)
    return res


def _advice(res: Result, specs) -> list[str]:
    tips = []
    for p in res.parts:
        if p.level is None:
            continue
        if p.name == "RAM" and p.level <= MINIMUM:
            tips.append("Close browsers and other apps before playing. More RAM is the cheapest big upgrade here."
                        if p.level >= BORDERLINE else
                        "RAM is the main problem. Adding RAM is cheap and would help the most.")
        elif p.name == "GPU" and p.level <= MINIMUM:
            tips.append("Lower the resolution (720p/900p), set textures and shadows to low, and turn off anti-aliasing "
                        "and ray tracing. Resolution matters most.")
        elif p.name == "CPU" and p.level <= MINIMUM:
            tips.append("Lower crowd/NPC density, view distance and physics settings, and cap fps to keep frame times steady.")
        elif p.name == "VRAM" and p.level <= MINIMUM:
            tips.append("Drop texture quality first. Running out of VRAM causes stutter even with a fast GPU.")
        elif p.name == "Disk" and p.level == BELOW:
            tips.append(f"Free up disk space: you need about {p.min_req} and have {p.yours}.")
    return list(dict.fromkeys(tips))
