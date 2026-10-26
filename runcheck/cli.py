from __future__ import annotations
import argparse, json, sys
from pathlib import Path

from . import specs as specmod
from .compare import compare, LABELS
from .steam import fetch_requirements, search_game

CACHE = Path.home() / ".runcheck" / "cache"


def load_requirements(app_id: int) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{app_id}.json"
    try:
        req = fetch_requirements(app_id)
        f.write_text(json.dumps(req))
        return req
    except Exception as e:
        if f.exists():
            print(f"(offline or Steam unavailable: using cached data. {e})", file=sys.stderr)
            return json.loads(f.read_text())
        raise


def pick_game(query: str) -> tuple[int, str]:
    if query.isdigit():
        return int(query), query
    results = search_game(query)
    if not results:
        sys.exit(f"No Steam game found for '{query}'.")
    if len(results) == 1 or results[0]["name"].lower() == query.lower():
        return results[0]["id"], results[0]["name"]
    print("Multiple matches:")
    for i, r in enumerate(results[:6], 1):
        print(f"  {i}. {r['name']}  (id {r['id']})")
    choice = input("Pick a number [1]: ").strip() or "1"
    r = results[int(choice) - 1]
    return r["id"], r["name"]


def show_specs(s):
    print(f"OS:    {s.os}\nCPU:   {s.cpu} ({s.cpu_cores} cores / {s.cpu_threads} threads)")
    for g in s.gpus:
        v = f"{g['vram_gb']} GB" if g.get("vram_gb") else "VRAM unknown"
        print(f"GPU:   {g['name']} ({v})")
    print(f"RAM:   {s.ram_gb} GB\nDisk:  {s.free_disk_gb} GB free")


def show_result(res):
    print(f"\n=== {res.game} ===")
    if res.verdict is None:
        print("Can't give a verdict: couldn't compare your CPU and/or GPU (see below). "
              "RAM and disk results alone aren't enough.")
    else:
        print(f"Verdict: {LABELS[res.verdict]}\n")
    print(f"{'':6}{'Yours':32}{'Minimum':26}{'Recommended':26}Status")
    names = {0: "BELOW", 1: "BORDERLINE", 2: "min", 3: "rec", 4: "exceeds"}
    for p in res.parts:
        status = names[p.level] if p.level is not None else f"? {p.note}"
        print(f"{p.name:6}{p.yours[:30]:32}{(p.min_req or '-')[:24]:26}{(p.rec_req or '-')[:24]:26}{status}")
    if res.bottleneck and res.verdict is not None and res.verdict < 4:
        print(f"\nWeakest part: {res.bottleneck.name}")
    for t in res.advice:
        print(f"  - {t}")
    if res.unknown:
        print("\nCouldn't compare: " + ", ".join(p.name for p in res.unknown) + ". Treat the verdict as less certain.")
    print("\nThese are estimates from published requirements, not benchmarks.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="runcheck", description="Can your PC run it?")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("specs", help="show detected hardware")
    c = sub.add_parser("check", help="check a Steam game")
    c.add_argument("game", help="game name or Steam app id")
    c.add_argument("--specs-file", help="JSON file to use instead of detecting (for testing other PCs)")
    a = ap.parse_args(argv)

    if a.cmd == "specs":
        show_specs(specmod.detect()); return
    if a.specs_file:
        s = specmod.Specs(**json.loads(Path(a.specs_file).read_text()))
    else:
        s = specmod.detect()
    app_id, name = pick_game(a.game)
    show_specs(s)
    show_result(compare(s, load_requirements(app_id)))


if __name__ == "__main__":
    main()
