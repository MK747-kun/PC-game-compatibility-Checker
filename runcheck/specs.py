"""Detect this PC's hardware. Windows-first, with Linux/macOS fallbacks."""
from __future__ import annotations
import json, platform, re, shutil, subprocess
from dataclasses import dataclass, asdict, field

import psutil


@dataclass
class Specs:
    os: str = ""
    cpu: str = ""
    cpu_cores: int = 0
    cpu_threads: int = 0
    gpus: list = field(default_factory=list)   # [{"name": str, "vram_gb": float|None}]
    ram_gb: float = 0.0
    free_disk_gb: float = 0.0

    def best_gpu(self):
        """Prefer a dedicated GPU: highest VRAM, ignoring virtual adapters."""
        real = [g for g in self.gpus if not re.search(r"(basic|virtual|remote|parsec|meta)", g["name"], re.I)]
        pool = real or self.gpus
        return max(pool, key=lambda g: g.get("vram_gb") or 0, default=None)

    def to_dict(self):
        return asdict(self)


def _run(cmd, timeout=15):
    # CREATE_NO_WINDOW stops a black console flashing up when the packaged app calls PowerShell
    flags = 0x08000000 if platform.system() == "Windows" else 0
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags).stdout
    except Exception:
        return ""


def _cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                name = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
                if name:
                    return name
        except Exception:
            pass
        out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"]).strip()
        if out:
            return out
    try:
        import cpuinfo
        name = cpuinfo.get_cpu_info().get("brand_raw")
        if name:
            return name
    except Exception:
        pass
    return platform.processor() or "Unknown CPU"


def _gpus_windows():
    # PowerShell works on modern Windows (wmic is removed in recent builds).
    # Win32_VideoController.AdapterRAM is a 32-bit field and caps at 4 GB,
    # so prefer nvidia-smi for NVIDIA cards when available.
    ps = ("Get-CimInstance Win32_VideoController | "
          "Select-Object Name,AdapterRAM | ConvertTo-Json")
    out = _run(["powershell", "-NoProfile", "-Command", ps])
    gpus = []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        for d in data:
            ram = d.get("AdapterRAM")
            gpus.append({"name": (d.get("Name") or "").strip(),
                         "vram_gb": round(ram / 1024**3, 1) if ram else None})
    except Exception:
        pass
    return _fix_nvidia_vram(gpus)


def _fix_nvidia_vram(gpus):
    if not shutil.which("nvidia-smi"):
        return gpus
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    for line in out.strip().splitlines():
        try:
            name, mem = [p.strip() for p in line.split(",")]
            mem_gb = round(float(mem) / 1024, 1)
        except ValueError:
            continue
        for g in gpus:
            if g["name"].lower() in name.lower() or name.lower() in g["name"].lower():
                g["vram_gb"] = mem_gb
                break
        else:
            gpus.append({"name": name, "vram_gb": mem_gb})
    return gpus


def _gpus_linux():
    gpus = []
    out = _run(["lspci"])
    for line in out.splitlines():
        if re.search(r"VGA|3D controller|Display controller", line):
            gpus.append({"name": line.split(": ", 1)[-1].strip(), "vram_gb": None})
    return _fix_nvidia_vram(gpus)


def _gpus_mac():
    out = _run(["system_profiler", "SPDisplaysDataType"])
    return [{"name": m.strip(), "vram_gb": None} for m in re.findall(r"Chipset Model:\s*(.+)", out)]


def detect() -> Specs:
    system = platform.system()
    if system == "Windows":
        gpus = _gpus_windows()
    elif system == "Darwin":
        gpus = _gpus_mac()
    else:
        gpus = _gpus_linux()
    disk_root = "C:\\" if system == "Windows" else "/"
    return Specs(
        os=f"{platform.system()} {platform.release()}",
        cpu=_cpu_name(),
        cpu_cores=psutil.cpu_count(logical=False) or 0,
        cpu_threads=psutil.cpu_count(logical=True) or 0,
        gpus=gpus,
        ram_gb=round(psutil.virtual_memory().total / 1024**3, 1),
        free_disk_gb=round(shutil.disk_usage(disk_root).free / 1024**3, 1),
    )
