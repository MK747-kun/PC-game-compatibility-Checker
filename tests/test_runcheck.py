import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from runcheck.steam import parse_requirements, split_alternatives
from runcheck.specs import Specs
from runcheck.compare import compare, BELOW, BORDERLINE, MINIMUM, RECOMMENDED, EXCEEDS

# Mirrors the HTML shape Steam's appdetails API returns.
MIN_HTML = ('<strong>Minimum:</strong><br><ul class="bb_ul"><li><strong>Requires a 64-bit processor and operating system</strong><br></li>'
            '<li><strong>OS *:</strong> Windows 10<br></li>'
            '<li><strong>Processor:</strong> Intel Core i5-4460 or AMD FX-6300<br></li>'
            '<li><strong>Memory:</strong> 8 GB RAM<br></li>'
            '<li><strong>Graphics:</strong> NVIDIA GeForce GTX 960 2GB or AMD Radeon R9 280X<br></li>'
            '<li><strong>Storage:</strong> 50 GB available space<br></li></ul>')
REC_HTML = ('<strong>Recommended:</strong><br><ul class="bb_ul"><li><strong>OS *:</strong> Windows 10/11<br></li>'
            '<li><strong>Processor:</strong> Intel Core i7-8700K / AMD Ryzen 5 3600X<br></li>'
            '<li><strong>Memory:</strong> 16 GB RAM<br></li>'
            '<li><strong>Graphics:</strong> NVIDIA GeForce GTX 1070 8 GB or AMD Radeon RX Vega 56 8 GB<br></li>'
            '<li><strong>Storage:</strong> 50 GB available space<br></li></ul>')
REQ = {"name": "Test Game", "minimum": parse_requirements(MIN_HTML), "recommended": parse_requirements(REC_HTML)}


def pc(cpu, gpu, vram, ram, disk=200):
    return Specs(os="Windows 10", cpu=cpu, cpu_cores=4, cpu_threads=8,
                 gpus=[{"name": gpu, "vram_gb": vram}], ram_gb=ram, free_disk_gb=disk)


def test_parse():
    m = REQ["minimum"]
    assert m["os"] == "Windows 10"
    assert m["ram_gb"] == 8 and m["storage_gb"] == 50
    assert "GTX 960" in m["gpu"] and "i5-4460" in m["cpu"]
    assert REQ["recommended"]["vram_gb"] == 8


def test_parse_empty_and_mb():
    assert parse_requirements("")["ram_gb"] is None
    assert parse_requirements("<li><strong>Memory:</strong> 512 MB RAM</li>")["ram_gb"] == 0.5
    assert parse_requirements("<li><strong>Storage:</strong> 1.5 TB</li>")["storage_gb"] == 1536


def test_alternatives():
    assert split_alternatives("Intel Core i5-4460 or AMD FX-6300") == ["Intel Core i5-4460", "AMD FX-6300"]
    assert len(split_alternatives("GTX 1070 8 GB or AMD Radeon RX Vega 56 8 GB")) == 2


def test_low_end_pc_fails():
    r = compare(pc("Intel(R) Core(TM) i3-4130 CPU @ 3.40GHz", "NVIDIA GeForce GT 730", 2, 4), REQ)
    assert r.verdict == BELOW


def test_minimum_pc():
    r = compare(pc("Intel(R) Core(TM) i5-4460 CPU @ 3.20GHz", "NVIDIA GeForce GTX 960", 2, 8), REQ)
    assert r.verdict == MINIMUM


def test_recommended_pc():
    r = compare(pc("AMD Ryzen 5 3600 6-Core Processor", "NVIDIA GeForce GTX 1070", 8, 16), REQ)
    assert r.verdict == RECOMMENDED


def test_high_end_pc():
    r = compare(pc("Intel(R) Core(TM) i7-13700K", "NVIDIA GeForce RTX 4080", 16, 32), REQ)
    assert r.verdict == EXCEEDS


def test_bottleneck_is_ram():
    r = compare(pc("AMD Ryzen 5 3600 6-Core Processor", "NVIDIA GeForce RTX 3070", 8, 4), REQ)
    assert r.verdict == BELOW and r.bottleneck.name == "RAM"
    assert any("RAM" in t for t in r.advice)


def test_disk_too_small():
    r = compare(pc("AMD Ryzen 5 3600 6-Core Processor", "NVIDIA GeForce GTX 1070", 8, 16, disk=10), REQ)
    assert r.verdict == BELOW and any("disk" in t.lower() for t in r.advice)


def test_unknown_hardware_does_not_crash():
    r = compare(pc("Mystery CPU 9000", "NVIDIA GeForce RTX 4080", 16, 32), REQ)
    assert [p for p in r.parts if p.name == "CPU"][0].level is None
    assert r.verdict is None and r.unknown      # can't promise a verdict without the CPU


# --- Regression: real report from a Windows 11 laptop (Haswell i3, HD Graphics) ---
DMC_MIN = ('<ul class="bb_ul"><li><strong>OS:</strong> Windows 7<br></li>'
           '<li><strong>Processor:</strong> Intel(R) Core(TM) 2 Duo 2.4 GHz<br></li>'
           '<li><strong>Memory:</strong> 2 GB RAM<br></li>'
           '<li><strong>Graphics:</strong> NVIDIA(R) GeForce(R) 8800 GTS<br></li>'
           '<li><strong>Storage:</strong> 27 GB available space<br></li></ul>')
DMC_REC = ('<ul class="bb_ul"><li><strong>Processor:</strong> Intel(R) Core(TM) i3 3.0 GHz<br></li>'
           '<li><strong>Memory:</strong> 2 GB RAM<br></li>'
           '<li><strong>Graphics:</strong> NVIDIA(R) GeForce(R) GTX 460<br></li></ul>')
DMC = {"name": "DMC4", "minimum": parse_requirements(DMC_MIN), "recommended": parse_requirements(DMC_REC)}


def test_laptop_regression_runs_dmc4():
    s = pc("Intel(R) Core(TM) i3-4010U CPU @ 1.70GHz", "Intel(R) HD Graphics Family", 1.0, 15.4, 46)
    r = compare(s, DMC)
    assert all(p.level is not None for p in r.parts if p.name in ("CPU", "GPU"))
    assert r.verdict is not None and r.verdict >= MINIMUM


def test_never_promises_when_cpu_and_gpu_unknown():
    s = pc("Intel64 Family 6 Model 69 Stepping 1, GenuineIntel", "Totally Unknown GPU", 16, 32, 500)
    r = compare(s, REQ)
    assert r.verdict is None      # RAM/disk alone must not produce "exceeds recommended"


def test_unknown_parts_still_report_certain_failure():
    s = pc("Mystery CPU", "Mystery GPU", 1.0, 2, 500)       # 2 GB RAM vs 8 GB minimum
    assert compare(s, REQ).verdict == BELOW


# --- v0.2: RAM rounding, disk handling, tailored reports ---
from runcheck.compare import nominal_ram
from runcheck.advice import build_report, pc_tier


def test_nominal_ram_snaps_to_installed_size():
    assert nominal_ram(7.8) == 8 and nominal_ram(15.4) == 16 and nominal_ram(31.9) == 32
    assert nominal_ram(5.0) == 5.0           # nothing sensible to snap to, so left alone


def test_8gb_pc_meets_8gb_requirement():
    r = compare(pc("AMD Ryzen 5 3600 6-Core Processor", "NVIDIA GeForce GTX 1070", 8, 7.8), REQ)
    assert [p for p in r.parts if p.name == "RAM"][0].level >= MINIMUM


def test_disk_only_failure_does_not_condemn_the_pc():
    s = pc("Intel(R) Core(TM) i7-13700K", "NVIDIA GeForce RTX 4080", 16, 32, disk=10)
    r = compare(s, REQ)
    assert r.verdict == BELOW and r.perf_verdict == EXCEEDS
    rep = build_report(s, r)
    assert "disk" in rep.headline.lower() and rep.verdict == EXCEEDS
    assert rep.resolution != "720p or below"


def test_reports_differ_by_pc_tier():
    weak = pc("Intel(R) Core(TM) i7-4510U CPU @ 2.00GHz", "Intel(R) HD Graphics Family", 1.0, 15.4, 46)
    strong = pc("Intel(R) Core(TM) i7-13700K", "NVIDIA GeForce RTX 4080", 16, 32, 800)
    rw, rs = build_report(weak, compare(weak, DMC)), build_report(strong, compare(strong, DMC))
    assert rw.tier == "Basic" and rs.tier == "Enthusiast"
    titles_w = [t for t, _ in rw.sections]; titles_s = [t for t, _ in rs.sections]
    assert "Get the most out of your PC" in titles_w and "Take advantage of your hardware" in titles_s
    assert rw.fps != rs.fps


def test_unknown_gpu_gives_unknown_tier():
    assert pc_tier(pc("x", "Mystery GPU", 4, 8))[0] == "Unknown"
