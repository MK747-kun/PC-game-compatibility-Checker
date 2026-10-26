"""Turn a comparison Result into a tailored, human-readable report.

The advice depends on two things: what the game needs (the verdict) and what kind of PC
the person has (the tier). A 2012 laptop and a gaming desktop get very different guidance,
including when the answer is "no".
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .compare import BELOW, BORDERLINE, MINIMUM, RECOMMENDED, EXCEEDS
from .scores import lookup

# ---- PC tiers (by GPU score, GTX 1060 6GB = 100) ----
TIERS = [
    (12,   "Basic",       "Built for everyday use and very light games: 2D/indie titles, older 3D games, and esports at low settings."),
    (40,   "Entry",       "Handles older 3D games, most indie games, and popular esports titles at 720p-900p on low settings."),
    (100,  "Budget gaming", "Plays most games at 1080p on low to medium settings, newer demanding games may need compromises."),
    (200,  "Mainstream",  "Solid 1080p gaming at high settings in most games, and 1440p in lighter ones."),
    (400,  "High-end",    "Strong 1440p gaming at high settings, and 4K in many games."),
    (10**9, "Enthusiast", "Max settings at 1440p or 4K, ray tracing and high refresh rates are realistic."),
]


@dataclass
class Report:
    game: str
    verdict: int | None
    headline: str
    summary: str
    tier: str
    tier_blurb: str
    settings: str = "-"
    resolution: str = "-"
    fps: str = "-"
    sections: list = field(default_factory=list)      # [(title, [bullet, ...]), ...]
    confidence: str = ""


def pc_tier(specs):
    gpu = specs.best_gpu()
    score, _ = lookup("gpus", gpu["name"]) if gpu else (None, None)
    if score is None:
        return "Unknown", "Your graphics card isn't in the score table yet, so results are less certain.", None
    for limit, name, blurb in TIERS:
        if score < limit:
            return name, blurb, score
    return TIERS[-1][1], TIERS[-1][2], score


def _is_integrated(gpu_name: str, vram) -> bool:
    n = (gpu_name or "").lower()
    return any(k in n for k in ("intel", "uhd", "iris", "hd graphics", "vega 3", "vega 8", "vega 11",
                                "radeon graphics", "610m", "660m", "680m", "780m"))


def _expected(res, specs, v):
    """Estimate settings / resolution / fps from how far the GPU and CPU are above the game's needs."""
    parts = {p.name: p for p in res.parts}
    g, c = parts.get("GPU"), parts.get("CPU")
    if v is None or g is None or g.vs_min is None:
        return "-", "-", "-"
    ratio = g.vs_rec if g.vs_rec is not None else g.vs_min * 1.5
    if v <= BELOW:
        return "Unplayable or very low", "720p or below", "Under 20-25 fps, with stutter"
    if v == BORDERLINE:
        return "Lowest", "720p", "20-30 fps, with drops"
    if ratio < 1.0:
        return "Low", "720p to 900p", "About 30 fps"
    if ratio < 1.5:
        return "Medium to High", "1080p", "About 60 fps"
    if ratio < 2.5:
        return "High", "1080p to 1440p", "60-100 fps"
    if ratio < 4:
        return "Ultra", "1440p", "100+ fps"
    return "Ultra (maximum)", "1440p to 4K", "100-144+ fps"


def _headline(v):
    if v is None:
        return "Not enough information for a full verdict"
    return {
        BELOW: "This game will not run well on your PC",
        BORDERLINE: "Just under the minimum: expect trouble",
        MINIMUM: "Playable at minimum settings",
        RECOMMENDED: "Runs well: you meet the recommended specs",
        EXCEEDS: "Runs great: you're well above the recommended specs",
    }[v]


def _summary(res, v):
    b = res.bottleneck
    if v is None:
        names = ", ".join(p.name for p in res.unknown) or "some parts"
        return (f"I couldn't compare your {names} against what {res.game} lists, so I can't promise a result. "
                "Everything I could check is shown below.")
    if v == BELOW:
        why = f"Your {b.name} is the main problem ({b.yours} vs {b.min_req or 'the minimum'})." if b else ""
        return f"{why} It may not start, or it may be too slow to enjoy."
    if v == BORDERLINE:
        return (f"Your {b.name} is just under the minimum. Some people get it running with the lowest settings, "
                "but crashes and low frame rates are likely.") if b else ""
    if v == MINIMUM:
        return (f"You meet the minimum, with your {b.name} as the weakest part. Expect low settings and "
                "a lower resolution to keep it smooth.") if b else ""
    if v == RECOMMENDED:
        return "Every part meets the recommended specs. Most settings can be set to high without trouble."
    return "Your PC is comfortably above what the game asks for, so you have room for higher resolution and extra effects."


# ---- Advice banks ----
def _weak_pc_tips(specs, res):
    gpu = specs.best_gpu()
    integrated = _is_integrated(gpu["name"] if gpu else "", gpu.get("vram_gb") if gpu else None)
    tips = []
    if integrated:
        tips += [
            "Your graphics are built into the processor and share system memory. Running two matching RAM sticks "
            "(dual-channel) can improve game speed noticeably.",
            "In Windows Settings > System > Display > Graphics, add the game and choose 'High performance'.",
        ]
    tips += [
        "Plug the laptop into power and set the Windows power mode to 'Best performance'. Battery mode slows both CPU and GPU.",
        "Close Chrome, Discord overlays and launchers before playing. Browsers can use gigabytes of RAM.",
        "Set the in-game resolution to 1280x720 first. Resolution has the biggest effect on frame rate.",
        "Turn off anti-aliasing, motion blur, shadows and ambient occlusion before touching anything else.",
        "Keep the PC cool: clean dust from the vents and avoid soft surfaces. Heat makes weak chips slow down.",
    ]
    return tips


def _strong_pc_tips(specs, res):
    return [
        "Turn on DLSS, FSR or XeSS if the game offers it. It raises frame rate with little visible loss.",
        "Cap the frame rate slightly under your monitor's refresh rate to keep it smooth and cool.",
        "Try a higher resolution or render scale before raising other settings. It's where the extra power shows most.",
    ]


def _upgrade_tips(res, specs):
    """Single most useful upgrade based on the weakest scored part."""
    b = res.bottleneck
    out = []
    parts = {p.name: p for p in res.parts}
    ram = parts.get("RAM")
    if ram and ram.level is not None and ram.level <= MINIMUM:
        out.append("RAM: add a stick or move to 16 GB. It's the cheapest upgrade and fixes stutter.")
    if b and b.name == "GPU" and b.level is not None and b.level <= MINIMUM:
        if specs.cpu_threads and specs.cpu_threads <= 4 and _is_integrated((specs.best_gpu() or {}).get("name", ""), None):
            out.append("GPU: on a laptop with integrated graphics, a better GPU usually isn't an option. "
                       "A desktop with even a used entry-level graphics card would be a large step up.")
        else:
            out.append("GPU: a graphics card upgrade would give the biggest improvement for this game.")
    if b and b.name == "CPU" and b.level is not None and b.level <= MINIMUM:
        out.append("CPU: a faster processor would help most here, since games with many characters rely on it heavily.")
    disk = parts.get("Disk")
    if disk and disk.level == BELOW:
        out.append(f"Storage: free up space. You need about {disk.min_req}.")
    elif disk is None or disk.level is not None:
        out.append("Storage: install games on an SSD if you can. It reduces load times and texture pop-in.")
    return out


def _if_it_wont_run(res, specs):
    return [
        "Check whether the game has a lighter older version, a 'classic' edition, or a demo you can try first.",
        "Steam lets you refund games within 14 days and under 2 hours of play, so testing a cheap game is low-risk.",
        "Cloud gaming (GeForce NOW, Xbox Cloud Gaming) runs the game on a remote PC. It needs a stable internet connection of about 15-25 Mbps.",
        "Look up the game's community pages for 'low spec' guides. Players often share config tweaks.",
    ]


def build_report(specs, res) -> Report:
    tier, blurb, _ = pc_tier(specs)
    pv = res.perf_verdict
    disk = next((p for p in res.parts if p.name == "Disk"), None)
    disk_blocked = res.verdict == BELOW and (pv is None or pv > BELOW) and disk is not None and disk.level == BELOW
    settings, resolution, fps = _expected(res, specs, pv)
    if disk_blocked:
        perf_line = _summary(res, pv).strip() if pv is not None else "I couldn't fully compare the rest of your hardware."
        headline = "Free up disk space first"
        summary = (f"There isn't enough free space to install it ({disk.yours} free, about {disk.min_req} needed). "
                   f"Once there's room: {perf_line[0].lower() + perf_line[1:]}")
    else:
        headline, summary = _headline(pv), _summary(res, pv).strip()
    r = Report(game=res.game, verdict=pv, headline=headline, summary=summary, tier=tier, tier_blurb=blurb,
               settings=settings, resolution=resolution, fps=fps)

    weak = pv is not None and pv <= MINIMUM
    if weak or tier in ("Basic", "Entry", "Unknown"):
        r.sections.append(("Get the most out of your PC", _weak_pc_tips(specs, res)))
    if pv is not None and pv >= RECOMMENDED and tier not in ("Basic", "Entry"):
        r.sections.append(("Take advantage of your hardware", _strong_pc_tips(specs, res)))
    # Per-part tips already computed in compare._advice, keep them, they're specific to this game.
    if res.advice:
        r.sections.insert(0, ("For this game", res.advice))
    if pv is not None and pv <= MINIMUM:
        r.sections.append(("Upgrade ideas, if you want to", _upgrade_tips(res, specs)))
    if pv is not None and pv <= BORDERLINE:
        r.sections.append(("If it still won't run", _if_it_wont_run(res, specs)))

    if res.unknown:
        r.confidence = ("Less certain: couldn't compare " + ", ".join(p.name for p in res.unknown) + ".")
    else:
        r.confidence = "Estimate from the game's published requirements, not a benchmark."
    return r
