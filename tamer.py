#!/usr/bin/env python3
"""
Tamer - Tame your server
========================
An unofficial Windows desktop manager for ARK: Survival Ascended dedicated
servers - one map or a whole cluster. Not affiliated with Studio Wildcard.

Features
  * Install / update / validate servers through SteamCMD (downloaded automatically)
  * Start, graceful stop (SaveWorld + DoExit over RCON), restart, force kill
  * Crash detection with automatic restart (with a crash-loop limit)
  * Scheduled daily restarts with in-game countdown warnings
  * Automatic "update released" detection -> warned restart + update
  * Config editor: common rates/rules form plus raw GameUserSettings.ini / Game.ini
  * RCON console, live player list (kick / ban), in-game chat feed
  * Automatic + manual save backups with retention, one-click restore
  * Multi-server clusters (shared -clusterid / -ClusterDirOverride)

Only the Python standard library is used (tkinter ships with the normal
Windows Python installer). Run:  python tamer.py
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
import math
import os
import queue
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
import zlib

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, font as tkfont

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
APP_NAME = "Tamer"
APP_TAGLINE = "Tame your server"
APP_VERSION = "1.18.3"
ASA_APP_ID = 2430930
IS_WINDOWS = os.name == "nt"

SERVER_EXE_REL = os.path.join("ShooterGame", "Binaries", "Win64", "ArkAscendedServer.exe")
SAVED_REL = os.path.join("ShooterGame", "Saved")
SAVEDARKS_REL = os.path.join("ShooterGame", "Saved", "SavedArks")
CONFIG_REL = os.path.join("ShooterGame", "Saved", "Config", "WindowsServer")
GAMELOG_REL = os.path.join("ShooterGame", "Saved", "Logs", "ShooterGame.log")

STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
BUILD_API_URL = f"https://api.steamcmd.net/v1/info/{ASA_APP_ID}"
DOCS_URL = "https://ark.wiki.gg/wiki/Server_configuration"
KOFI_URL = "https://ko-fi.com/tamerarkmanager"
TAMER_REPO = "adam32885/Tamer"
TAMER_RELEASE_API = os.environ.get("ASM_TAMER_API", f"https://api.github.com/repos/{TAMER_REPO}/releases/latest")
TAMER_RELEASES_PAGE = f"https://github.com/{TAMER_REPO}/releases"

# CurseForge (ASA mods). A free personal API key from console.curseforge.com is recommended;
# without one the manager falls back to the unofficial curse.tools proxy.
CF_GAME_ID = 83374
CF_API_BASE = "https://api.curseforge.com/v1"
CF_PROXY_BASE = "https://api.curse.tools/v1/cf"  # mirrors api.curseforge.com/v1
CF_CONSOLE_URL = "https://console.curseforge.com/"
CF_SORTS = [("Popularity", 2, "desc"), ("Last updated", 3, "desc"),
            ("Total downloads", 6, "desc"), ("Name", 4, "asc")]

MAPS = [
    ("The Island", "TheIsland_WP"),
    ("Scorched Earth", "ScorchedEarth_WP"),
    ("The Center", "TheCenter_WP"),
    ("Aberration", "Aberration_WP"),
    ("Extinction", "Extinction_WP"),
    ("Ragnarok", "Ragnarok_WP"),
    ("Valguero", "Valguero_WP"),
    ("Genesis", "Genesis_WP"),
    ("Astraeos (DLC)", "Astraeos_WP"),
    ("Lost Colony (DLC)", "LostColony_WP"),
]
MAP_IDS = [m[1] for m in MAPS]
MAP_LABELS = {m[1]: m[0] for m in MAPS}

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "manager_data")
RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)  # PyInstaller unpacks bundled files here
ICON_ICO = os.path.join(RESOURCE_DIR, "tamer.ico")
ICON_PNG = os.path.join(RESOURCE_DIR, "tamer.png")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
DETACHED_FLAGS = (0x00000008 | 0x00000200) if IS_WINDOWS else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP

# ARK's own rolling save copies (e.g. TheIsland_WP_02.11.2026_04.00.00.ark) - skipped in backups
ARK_ROLLING_BACKUP_RE = re.compile(r"_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}\.ark$", re.I)
PLAYER_LINE_RE = re.compile(r"^\s*(\d+)\.\s*(.*?),\s*(\S+)\s*$")
NO_RESPONSE = "Server received, But no response"


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "server"


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def parse_times(text: str) -> list[tuple[int, int]]:
    """'04:00, 16:30' -> [(4,0),(16,30)]"""
    out = []
    for part in re.split(r"[,\s;]+", text.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", part)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError(f"Invalid time '{part}' (use HH:MM, 24-hour)")
        out.append((int(m.group(1)), int(m.group(2))))
    return out


def parse_minutes(text: str) -> list[int]:
    out = []
    for part in re.split(r"[,\s;]+", text.strip()):
        if part:
            if not part.isdigit() or int(part) <= 0:
                raise ValueError(f"Invalid minutes value '{part}'")
            out.append(int(part))
    return sorted(set(out), reverse=True)


def staggered_times(times_text: str, offset_minutes: int) -> str:
    """'04:00, 16:00' shifted by 25 min -> '04:25, 16:25' (wraps past midnight)."""
    shifted = sorted({(h * 60 + m + offset_minutes) % 1440 for h, m in parse_times(times_text)})
    return ", ".join(f"{t // 60:02d}:{t % 60:02d}" for t in shifted)


def next_occurrence(times, now: dt.datetime):
    best = None
    for h, m in times:
        cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= now:
            cand += dt.timedelta(days=1)
        if best is None or cand < best:
            best = cand
    return best


def read_text_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    raw = open(path, "rb").read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def write_text_file(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\r\n" if IS_WINDOWS else "\n") as f:
        f.write(text)
    os.replace(tmp, path)


def open_path(path: str):
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:  # pragma: no cover
        messagebox.showerror(APP_NAME, f"Could not open {path}\n{e}")


_K32 = None


def _kernel32():
    """kernel32 with proper 64-bit handle types (kept separate from ctypes.windll)."""
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4
        k.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        k.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
        _K32 = k
    return _K32


def pid_alive(pid) -> bool:
    if not pid:
        return False
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        k32 = _kernel32()
        handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def ark_log_windows(pids, hidden=False) -> list:
    """Visible (or, with hidden=True, hidden) top-level windows of these processes that are ARK's own log window:
    Unreal's console, window class "FConsoleWindow", titled "Server Console (ArkAscendedServer) - <path>" (the
    "ASA 96.9 | ..." line is drawn inside it). AsaApi's window is a normal Windows console ("ConsoleWindowClass"),
    so it's left alone."""
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32  # type: ignore[attr-defined]
    pids, found = {int(p) for p in pids if p}, []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and bool(u.IsWindowVisible(hwnd)) != hidden:
            cls = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(hwnd, cls, 256)
            if cls.value == "FConsoleWindow":
                found.append(hwnd)
        return True
    u.EnumWindows(each, 0)
    return found


def hide_ark_log(s) -> bool:
    """Hide this server's ARK log window? Only when it runs through AsaApi, whose own window then stays, so there's
    always one window for the server."""
    return bool(s.get("hide_log_window", True) and s.get("asaapi"))


def show_window(hwnd, show: bool) -> bool:
    """Hide or show a window. False if it's gone."""
    if not IS_WINDOWS:
        return False
    import ctypes
    u = ctypes.windll.user32  # type: ignore[attr-defined]
    if not u.IsWindow(hwnd):
        return False
    u.ShowWindow(hwnd, 5 if show else 0)  # SW_SHOW / SW_HIDE
    return True


def kill_pid(pid):
    if not pid:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)
    else:
        try:
            os.kill(int(pid), 9)
        except OSError:
            pass


def process_stats(pid):
    """Return (total_cpu_seconds, memory_bytes) for a process, or None. Memory = working set (as in Task Manager)."""
    if not pid:
        return None
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        k32 = _kernel32()
        h = k32.OpenProcess(0x1000 | 0x0010, False, int(pid)) or k32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return None
        try:
            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                            ("PrivateUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            mem = pmc.WorkingSetSize if k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb) else None
            ft = [wintypes.FILETIME() for _ in range(4)]
            cpu = None
            if k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
                cpu = sum((f.dwHighDateTime << 32 | f.dwLowDateTime) for f in ft[2:]) / 1e7
            return cpu, mem
        finally:
            k32.CloseHandle(h)
    try:  # Linux (used for testing)
        with open(f"/proc/{int(pid)}/stat") as f:
            parts = f.read().rsplit(")", 1)[1].split()
        cpu = (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")
        mem = None
        with open(f"/proc/{int(pid)}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    mem = int(line.split()[1]) * 1024
        return cpu, mem
    except (OSError, ValueError, IndexError):
        return None


def system_memory():
    """(used_bytes, total_bytes) for the whole machine, or (0, 0)."""
    try:
        if IS_WINDOWS:
            import ctypes
            from ctypes import wintypes

            class MSX(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MSX()
            m.dwLength = ctypes.sizeof(MSX)
            if _kernel32().GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.ullTotalPhys - m.ullAvailPhys, m.ullTotalPhys
            return 0, 0
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        return info["MemTotal"] - info.get("MemAvailable", 0), info["MemTotal"]
    except Exception:
        return 0, 0


def gb(n) -> str:
    return f"{(n or 0) / 1024 ** 3:.1f} GB"


def format_duration(seconds) -> str:
    seconds = int(seconds or 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d {h}h" if d else f"{h}h {m:02d}m" if h else f"{m}m"


def scan_server_processes() -> list[tuple[int, str, str]]:
    """Return (pid, exe_path, command_line) for every running ArkAscendedServer.exe."""
    if not IS_WINDOWS:  # Linux/Proton: look through /proc
        out = []
        for d in os.listdir("/proc") if os.path.isdir("/proc") else []:
            if not d.isdigit():
                continue
            try:
                with open(f"/proc/{d}/cmdline", "rb") as f:
                    args = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
            except OSError:
                continue
            exe = next((a for a in args[:3] if a.endswith("ArkAscendedServer.exe")), None)
            if exe:
                out.append((int(d), exe, " ".join(args)))
        return out
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='ArkAscendedServer.exe'\" | "
          "ForEach-Object { \"$($_.ProcessId)`t$($_.ExecutablePath)`t$($_.CommandLine)\" }")
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=45, creationflags=CREATE_NO_WINDOW)
    except Exception:
        return []
    out = []
    for line in res.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].strip().isdigit():
            out.append((int(parts[0]), parts[1].strip(), parts[2]))
    return out


# --------------------------------------------------------------------------------------
# INI helpers (line-preserving; ARK ini files can contain duplicate keys, so no configparser)
# --------------------------------------------------------------------------------------
def _section_bounds(lines, section):
    target = section.strip().lower()
    start = None
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            if start is not None:
                return start, i
            if st[1:-1].strip().lower() == target:
                start = i
    return (start, len(lines)) if start is not None else None


def ini_get(text: str, section: str, key: str):
    lines = text.splitlines()
    b = _section_bounds(lines, section)
    if not b:
        return None
    for line in lines[b[0] + 1:b[1]]:
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip().lower() == key.lower():
                return v.strip()
    return None


def ini_set(text: str, section: str, key: str, value):
    """Set key=value inside [section]; value None removes the key."""
    lines = text.splitlines()
    b = _section_bounds(lines, section)
    if b is None:
        if value is None:
            return text
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines += [f"[{section}]", f"{key}={value}"]
    else:
        s, e = b
        out = lines[:s + 1]
        found = False
        for line in lines[s + 1:e]:
            if "=" in line and line.split("=", 1)[0].strip().lower() == key.lower():
                if not found and value is not None:
                    out.append(f"{key}={value}")
                found = True
                continue
            out.append(line)
        if not found and value is not None:
            j = len(out)
            while j > s + 1 and not out[j - 1].strip():
                j -= 1
            out.insert(j, f"{key}={value}")
        lines = out + lines[e:]
    return "\n".join(lines) + "\n"


# Common settings shown in the form editor: (file, section, key, label, hint, kind)
GUS = "GameUserSettings.ini"
GINI = "Game.ini"
SS = "ServerSettings"
GM = "/script/shootergame.shootergamemode"
COMMON_SETTINGS = [
    ("Rates", [
        (GUS, SS, "XPMultiplier", "XP multiplier", "1.0", "num"),
        (GUS, SS, "TamingSpeedMultiplier", "Taming speed", "1.0", "num"),
        (GUS, SS, "HarvestAmountMultiplier", "Harvest amount", "1.0", "num"),
        (GUS, SS, "HarvestHealthMultiplier", "Resource health", "1.0", "num"),
        (GUS, SS, "ResourcesRespawnPeriodMultiplier", "Resource respawn period", "1.0 (lower = faster)", "num"),
        (GINI, GM, "CropGrowthSpeedMultiplier", "Crop growth speed", "1.0", "num"),
        (GINI, GM, "SupplyCrateLootQualityMultiplier", "Supply crate loot quality", "1.0", "num"),
        (GINI, GM, "FishingLootQualityMultiplier", "Fishing loot quality", "1.0", "num"),
    ]),
    ("Difficulty & survival", [
        (GUS, SS, "OverrideOfficialDifficulty", "Override difficulty", "5.0 = level 150 wild dinos", "num"),
        (GUS, SS, "DifficultyOffset", "Difficulty offset", "1.0", "num"),
        (GUS, SS, "PlayerDamageMultiplier", "Player damage", "1.0", "num"),
        (GUS, SS, "DinoDamageMultiplier", "Dino damage", "1.0", "num"),
        (GUS, SS, "PlayerCharacterFoodDrainMultiplier", "Player food drain", "1.0", "num"),
        (GUS, SS, "PlayerCharacterWaterDrainMultiplier", "Player water drain", "1.0", "num"),
        (GUS, SS, "PlayerCharacterStaminaDrainMultiplier", "Player stamina drain", "1.0", "num"),
        (GUS, SS, "DinoCharacterFoodDrainMultiplier", "Dino food drain", "1.0", "num"),
        (GUS, SS, "DayCycleSpeedScale", "Day cycle speed", "1.0", "num"),
        (GUS, SS, "DayTimeSpeedScale", "Daytime speed", "1.0", "num"),
        (GUS, SS, "NightTimeSpeedScale", "Night-time speed", "1.0", "num"),
    ]),
    ("Breeding", [
        (GINI, GM, "MatingIntervalMultiplier", "Mating interval", "1.0 (lower = shorter)", "num"),
        (GINI, GM, "EggHatchSpeedMultiplier", "Egg hatch speed", "1.0", "num"),
        (GINI, GM, "BabyMatureSpeedMultiplier", "Baby mature speed", "1.0", "num"),
        (GINI, GM, "BabyCuddleIntervalMultiplier", "Cuddle interval", "1.0 (lower = more often)", "num"),
        (GINI, GM, "BabyImprintingStatScaleMultiplier", "Imprint stat bonus", "1.0", "num"),
        (GINI, GM, "BabyFoodConsumptionSpeedMultiplier", "Baby food consumption", "1.0", "num"),
    ]),
    ("Rules", [
        (GUS, SS, "ServerPVE", "PvE server", "False", "bool"),
        (GUS, SS, "AllowThirdPersonPlayer", "Allow third person", "True", "bool"),
        (GUS, SS, "ShowMapPlayerLocation", "Show player on map", "True", "bool"),
        (GUS, SS, "ServerCrosshair", "Crosshair", "True", "bool"),
        (GUS, SS, "AllowFlyerCarryPvE", "Flyer carry in PvE", "False", "bool"),
        (GUS, SS, "AllowCaveBuildingPvE", "Cave building in PvE", "False", "bool"),
        (GUS, SS, "DisableStructureDecayPvE", "Disable structure decay (PvE)", "False", "bool"),
        (GUS, SS, "AlwaysAllowStructurePickup", "Always allow structure pickup", "False", "bool"),
        (GINI, GM, "bAllowUnlimitedRespecs", "Unlimited mindwipes", "False", "bool"),
        (GINI, GM, "bAllowFlyerSpeedLeveling", "Flyer speed leveling", "False", "bool"),
        (GINI, GM, "MaxNumberOfPlayersInTribe", "Max players per tribe", "0 = unlimited", "num"),
        (GUS, SS, "MaxTamedDinos", "Max tamed dinos (server)", "5000", "num"),
        (GUS, SS, "AutoSavePeriodMinutes", "Autosave every (min)", "15", "num"),
    ]),
    ("Cluster transfers", [
        (GUS, SS, "PreventDownloadSurvivors", "Block survivor downloads", "False", "bool"),
        (GUS, SS, "PreventDownloadItems", "Block item downloads", "False", "bool"),
        (GUS, SS, "PreventDownloadDinos", "Block dino downloads", "False", "bool"),
        (GUS, SS, "PreventUploadSurvivors", "Block survivor uploads", "False", "bool"),
        (GUS, SS, "PreventUploadItems", "Block item uploads", "False", "bool"),
        (GUS, SS, "PreventUploadDinos", "Block dino uploads", "False", "bool"),
    ]),
    ("Message of the day", [
        (GUS, "MessageOfTheDay", "Message", "MOTD text", "use \\n for new lines", "text"),
        (GUS, "MessageOfTheDay", "Duration", "MOTD duration (s)", "20", "num"),
    ]),
]


# --------------------------------------------------------------------------------------
# Source RCON client (ARK uses the Valve Source RCON protocol over TCP)
# --------------------------------------------------------------------------------------
class RconError(Exception):
    pass


class RconAuthError(RconError):
    pass


class RconClient:
    AUTH, EXEC, AUTH_RESPONSE = 3, 2, 2

    def __init__(self, host: str, port: int, password: str, timeout: float = 4.0):
        self.host, self.port, self.password, self.timeout = host, port, password, timeout
        self.sock = None
        self._id = 0
        self.lock = threading.Lock()

    def _send(self, ptype: int, body: str) -> int:
        self._id = self._id % 2_000_000_000 + 1
        payload = struct.pack("<ii", self._id, ptype) + body.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(payload)) + payload)
        return self._id

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RconError("RCON connection closed by server")
            buf += chunk
        return buf

    def _recv(self):
        size = struct.unpack("<i", self._recv_exact(4))[0]
        if size < 10 or size > 4_000_000:
            raise RconError(f"Bad RCON packet size {size}")
        data = self._recv_exact(size)
        rid, rtype = struct.unpack("<ii", data[:8])
        return rid, rtype, data[8:-2].decode("utf-8", "replace")

    def connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        rid = self._send(self.AUTH, self.password)
        while True:
            r, t, _ = self._recv()
            if t == self.AUTH_RESPONSE:
                if r == -1:
                    self.close()
                    raise RconAuthError("RCON authentication failed - check the admin password")
                if r == rid:
                    return

    def command(self, cmd: str) -> str:
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.sock is None:
                        self.connect()
                    rid = self._send(self.EXEC, cmd)
                    while True:
                        r, _t, body = self._recv()
                        if r == rid:
                            return body.strip()
                except RconAuthError:
                    raise
                except (OSError, RconError):
                    self.close()
                    if attempt == 2:
                        raise
        return ""

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None


def parse_players(text: str) -> list[tuple[str, str, str]]:
    players = []
    for line in text.splitlines():
        m = PLAYER_LINE_RE.match(line)
        if m:
            players.append((m.group(1), m.group(2), m.group(3)))
    return players


# --------------------------------------------------------------------------------------
# CurseForge mod catalogue
# --------------------------------------------------------------------------------------
def short_number(n) -> str:
    n = float(n or 0)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n:.0f}"


def normalize_mod(m: dict) -> dict:
    authors = m.get("authors") or []
    links = m.get("links") or {}
    slug = m.get("slug") or ""
    files = m.get("latestFiles") or []
    file_id = m.get("mainFileId") or max((f.get("id") or 0 for f in files), default=0) or None
    return {
        "id": str(m.get("id")),
        "name": m.get("name") or f"Mod {m.get('id')}",
        "author": authors[0].get("name", "") if authors else "",
        "downloads": int(m.get("downloadCount") or 0),
        "updated": (m.get("dateModified") or m.get("dateReleased") or "")[:10],
        "summary": m.get("summary") or "",
        "categories": [c.get("name", "") for c in (m.get("categories") or [])],
        "file_id": str(file_id) if file_id else None,
        "url": links.get("websiteUrl") or (f"https://www.curseforge.com/ark-survival-ascended/mods/{slug}"
                                           if slug else ""),
    }


def clean_api_key(raw) -> str:
    """Undo common copy/paste damage: spaces, quotes, invisible characters, a pasted 'x-api-key:' prefix."""
    k = str(raw or "")
    for ch in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00a0"):
        k = k.replace(ch, "")
    k = k.strip()
    if k.lower().startswith("x-api-key"):
        k = k[len("x-api-key"):].lstrip(" :=\t")
    k = k.strip().strip("\"'`\u201c\u201d\u2018\u2019").strip()
    return "".join(k.split())


def api_key_format_problem(key: str) -> str:
    """CurseForge console keys look like $2a$10$ followed by 53 characters (60 in total)."""
    if not key:
        return ""
    if not key.startswith("$2a$"):
        return ("It doesn't look like a CurseForge API key - those start with $2a$10$. Make sure you copied the "
                "API key from console.curseforge.com > API keys, not an author/project token.")
    if len(key) != 60:
        return f"It's {len(key)} characters long; CurseForge API keys are 60. Part of it may be missing."
    return ""


KEY_REJECTED_HELP = ("Fixes that usually work:\n"
                     "  1. On console.curseforge.com > API keys, copy the key again with the copy button and "
                     "paste it into File > Settings (use Test key).\n"
                     "  2. If that still fails, the key has been revoked - generate a new one there.\n"
                     "  3. Or clear the key field to use the free proxy instead.")


class CurseForge:
    def __init__(self, key_getter):
        self.key_getter = key_getter
        self.base_override = os.environ.get("ASM_CF_BASE")  # for testing
        self.key_problem = ""      # set when the personal key was rejected and we fell back to the proxy
        self._rejected_key = None  # the key value that was rejected (cleared when the key changes)

    def key(self) -> str:
        return clean_api_key(self.key_getter())

    def using_proxy(self) -> bool:
        k = self.key()
        return not self.base_override and (not k or k == self._rejected_key)

    def _http(self, path, params, body, key):
        base = self.base_override or (CF_API_BASE if key else CF_PROXY_BASE)
        url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/json", "User-Agent": f"Tamer/{APP_VERSION}"}
        if key:
            headers["x-api-key"] = key
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)

    def _request(self, path, params=None, body=None):
        key = self.key()
        if key and key == self._rejected_key:
            key = ""  # already known bad this session - go straight to the proxy
        elif key:
            self.key_problem = ""
        try:
            return self._http(path, params, body, key)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and key:
                # Personal key rejected: remember it and retry through the free proxy so mod search keeps working.
                self._rejected_key = key
                fmt = api_key_format_problem(key)
                self.key_problem = (f"CurseForge rejected your API key (HTTP {e.code})."
                                    + (f" {fmt}" if fmt else "")
                                    + " Mod search is using the free proxy for now.\n\n" + KEY_REJECTED_HELP)
                try:
                    return self._http(path, params, body, "")
                except Exception as e2:
                    raise RuntimeError(f"CurseForge rejected your API key (HTTP {e.code}), and the free proxy "
                                       f"didn't work either ({e2}).\n\n{KEY_REJECTED_HELP}")
            if e.code in (401, 403):
                raise RuntimeError("The free CurseForge proxy refused the request (HTTP %d). Add your own free "
                                   "CurseForge API key in File > Settings." % e.code)
            where = "the free CurseForge proxy" if not key and not self.base_override else "CurseForge"
            hint = ("" if key else "\n\nIf this keeps happening, add your own free CurseForge API key in "
                                   "File > Settings (get one at console.curseforge.com).")
            raise RuntimeError(f"{where} returned HTTP {e.code} for {path}.{hint}")
        except urllib.error.URLError as e:
            hint = "" if key else " The free proxy may be down - adding your own CurseForge API key in File > Settings is more reliable."
            raise RuntimeError(f"Couldn't reach CurseForge: {e.reason}.{hint}")

    def test_key(self, raw):
        """Returns (ok, message) for the Settings 'Test key' button. Never falls back to the proxy."""
        key = clean_api_key(raw)
        if not key:
            return False, "The key field is empty. Without a key, mod search uses the free proxy."
        try:
            res = self._http("/games/" + str(CF_GAME_ID), None, None, key)
            name = (res.get("data") or {}).get("name", "ARK: Survival Ascended")
            if key == self._rejected_key:
                self._rejected_key, self.key_problem = None, ""
            return True, f"The key works - CurseForge answered for {name}."
        except urllib.error.HTTPError as e:
            fmt = api_key_format_problem(key)
            if e.code in (401, 403):
                return False, (f"CurseForge rejected this key (HTTP {e.code}).\n\n" + (fmt + "\n\n" if fmt else "")
                               + KEY_REJECTED_HELP)
            return False, f"CurseForge returned HTTP {e.code}. Try again in a minute."
        except urllib.error.URLError as e:
            return False, f"Couldn't reach CurseForge: {e.reason}."

    def search(self, text: str, sort_label: str = "Popularity", index: int = 0, page_size: int = 50):
        field, order = next(((f, o) for lbl, f, o in CF_SORTS if lbl == sort_label), (2, "desc"))
        params = {"gameId": CF_GAME_ID, "sortField": field, "sortOrder": order,
                  "index": index, "pageSize": page_size}
        if text.strip():
            params["searchFilter"] = text.strip()
        res = self._request("/mods/search", params)
        mods = [normalize_mod(m) for m in res.get("data", [])]
        total = (res.get("pagination") or {}).get("totalCount", len(mods))
        return mods, int(total)

    def get_mods(self, ids):
        """Details of these mods. Asks for them all at once; when that's refused (the free proxy stopped answering
        POST /mods in 2026: HTTP 404), asks for each one on its own, a few at a time. Mods CurseForge doesn't
        know are left out; it only raises if not one could be fetched."""
        ids = [int(i) for i in ids if str(i).isdigit()]
        if not ids:
            return []
        if not getattr(self, "_batch_refused", False):
            try:
                res = self._request("/mods", body={"modIds": ids})
                return [normalize_mod(m) for m in res.get("data", [])]
            except RuntimeError as e:
                if not re.search(r"HTTP 40[45]\b", str(e)):
                    raise
                self._batch_refused = True  # don't keep asking for batches this session
        found, errors = {}, []

        def one(mid):
            try:
                found[mid] = normalize_mod(self._request(f"/mods/{mid}")["data"])
            except (RuntimeError, KeyError, TypeError) as e:
                errors.append(e)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(one, ids))
        if not found and errors:
            raise errors[0] if isinstance(errors[0], RuntimeError) else RuntimeError(str(errors[0]))
        return [found[i] for i in ids if i in found]


# --------------------------------------------------------------------------------------
# Discord webhook notifications
# --------------------------------------------------------------------------------------
DISCORD_EVENTS = [
    ("status", "Server online / stopped"),
    ("crash", "Crashes"),
    ("restart", "Restarts and shutdown countdowns"),
    ("update", "Game and mod updates"),
    ("players", "Players joining / leaving"),
    ("resources", "High memory alerts"),
    ("backups", "Backup problems"),
    ("diagnose", "Startup problems found"),
]
DISCORD_COLORS = {"good": 0x1A7F37, "bad": 0xCF222E, "warn": 0xBF8700, "info": 0x0969DA, "muted": 0x6E7781}


class DiscordNotifier:
    def __init__(self, cfg, on_error):
        self.cfg = cfg
        self.on_error = on_error
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name="discord").start()

    def enabled(self, event: str) -> bool:
        d = self.cfg.data
        return bool(d.get("discord_webhook", "").strip()) and bool(d.get("discord_events", {}).get(event, True))

    def payload(self, server_name, title, desc="", color="info"):
        embed = {"title": (f"{server_name} · {title}" if server_name else title)[:256],
                 "color": DISCORD_COLORS.get(color, color if isinstance(color, int) else DISCORD_COLORS["info"]),
                 "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}
        if desc:
            embed["description"] = desc[:4000]
        return {"username": (self.cfg.data.get("discord_name") or APP_NAME)[:80],
                "embeds": [embed], "allowed_mentions": {"parse": []}}

    def send(self, event, server_name, title, desc="", color="info"):
        if self.enabled(event):
            self.q.put((self.cfg.data["discord_webhook"].strip(), self.payload(server_name, title, desc, color)))

    @staticmethod
    def post(url: str, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        for _ in range(4):
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Content-Type": "application/json", "User-Agent": f"Tamer/{APP_VERSION}"})
            try:
                urllib.request.urlopen(req, timeout=15).close()
                return
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    try:
                        wait = float(json.load(e).get("retry_after", 2))
                    except Exception:
                        wait = 2.0
                    time.sleep(min(max(wait, 0.5), 30))
                    continue
                hint = " - check the webhook URL" if e.code in (400, 401, 403, 404) else ""
                raise RuntimeError(f"Discord returned HTTP {e.code}{hint}")
            except urllib.error.URLError as e:
                raise RuntimeError(f"Couldn't reach Discord: {e.reason}")
        raise RuntimeError("Discord kept rate-limiting the webhook")

    def _worker(self):
        while True:
            url, payload = self.q.get()
            try:
                self.post(url, payload)
            except Exception as e:
                self.on_error(f"Discord notification failed: {e}")
            time.sleep(0.4)


# --------------------------------------------------------------------------------------
# Command-line launch options (the "Command line" tab)
# --------------------------------------------------------------------------------------
# (group, [(flag, label, hint)]) - flags are added as-is to the launch command when ticked
CMD_FLAG_GROUPS = [
    ("Creatures", [
        ("-ForceRespawnDinos", "Respawn all wild dinos at startup", ""),
        ("-NoWildBabies", "No wild babies", ""),
        ("-ForceAllowCaveFlyers", "Allow flyers in caves", ""),
        ("-UnstasisDinoObstructionCheck", "Unstasis dino obstruction check", "Stops dinos waking inside structures"),
        ("-AlwaysTickDedicatedSkeletalMeshes", "Always tick dedicated skeletal meshes", "Fixes some hitbox issues; costs CPU"),
        ("-DisableDinoNetRangeScaling", "Disable dino net range scaling", "Advanced"),
        ("-NoDinos", "No dinos at all", "Empty map"),
        ("-NoDinosExceptForcedSpawn", "No dinos except forced spawns", "Advanced"),
        ("-NoDinosExceptStreamingSpawn", "No dinos except streaming spawns", "Advanced"),
        ("-NoDinosExceptManualSpawn", "No dinos except manual spawns", "Advanced"),
        ("-NoDinosExceptWaterSpawn", "No dinos except water spawns", "Advanced"),
        ("-NoAI", "No creature AI", "Testing only"),
    ]),
    ("Server mechanics", [
        ("-servergamelog", "Server game log", "Recommended - Tamer's troubleshooter reads it"),
        ("-servergamelogincludetribelogs", "Game log includes tribe logs", ""),
        ("-ServerRCONOutputTribeLogs", "Send tribe logs to RCON", "Shows tribe logs in the console / chat feed"),
        ("-exclusivejoin", "Whitelist only (exclusive join)", "Only players on the allow list can join"),
        ("-AutoDestroyStructures", "Auto-destroy old structures", "Uses the decay settings"),
        ("-disablecharactertracker", "Disable character tracker", ""),
        ("-UseServerNetSpeedCheck", "Use server net speed check", "Helps against speed exploits"),
        ("-StasisKeepControllers", "Stasis keep controllers", "Uses more memory; can help AI on big maps"),
        ("-ignoredupeditems", "Ignore duped items", ""),
        ("-UseDynamicConfig", "Use dynamic config", "Lets official-style dynamic config change rates live"),
        ("-DisableCustomCosmetics", "Disable custom cosmetics", ""),
    ]),
    ("Anti-cheat & protection", [
        ("-noundermeshchecking", "Disable under-mesh checking", ""),
        ("-noundermeshkilling", "Disable under-mesh killing", ""),
        ("-noantispeedhack", "Disable anti speed-hack", ""),
        ("-nohangdetection", "Disable hang detection", "Stops the server killing itself on long hitches"),
        ("-DoCustomCosmeticValidation", "Validate custom cosmetics", ""),
        ("-PrintCosmeticCRC", "Log cosmetic CRC", "Debugging"),
    ]),
    ("Cluster transfers", [
        ("-NoTransferFromFiltering", "No transfer-from filtering", "Lets cluster servers accept each other's uploads"),
    ]),
    ("Threads (advanced)", [
        ("-OneThread", "One thread", "Leave all of these off unless you know you need one"),
        ("-ForceUsePerfThreads", "Force use perf threads", ""),
        ("-NoPerfThreads", "No perf threads", ""),
    ]),
]
CMD_FLAGS = {f for _g, items in CMD_FLAG_GROUPS for f, _l, _h in items}
CULTURES = ["", "ca", "cs", "da", "de", "en", "es", "eu", "fi", "fr", "hu", "it", "ja", "ka", "ko", "nl", "pl",
            "pt_BR", "ru", "sv", "th", "tr", "zh", "zh-Hans-CN", "zh-TW"]
PLATFORM_CHOICES = [("", "PC only (default)"), ("ALL", "All platforms - PC, Xbox and PlayStation (crossplay)"),
                    ("PC+XSX", "PC + Xbox"), ("PC+PS5", "PC + PlayStation")]
CPU_PRIORITIES = ["Idle", "Below normal", "Normal", "Above normal", "High"]
_WIN_PRIORITY = {"Idle": 0x40, "Below normal": 0x4000, "Normal": 0x20, "Above normal": 0x8000, "High": 0x80}
_NICE = {"Idle": 19, "Below normal": 10, "Normal": 0, "Above normal": -5, "High": -10}


def apply_process_cpu(pid, priority="Normal", cores=None) -> str:
    """Set a process's CPU priority and core affinity. Returns '' or an error description."""
    if not pid:
        return "not running"
    cores = sorted({int(c) for c in (cores or [])})
    errors = []
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        k32 = _kernel32()
        k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        h = k32.OpenProcess(0x0200 | 0x0400, False, int(pid))  # SET_INFORMATION | QUERY_INFORMATION
        if not h:
            return "Windows refused access to the server process (run Tamer as the same user that started it)"
        try:
            if not k32.SetPriorityClass(h, _WIN_PRIORITY.get(priority, 0x20)):
                errors.append("priority")
            if cores:
                mask = sum(1 << c for c in cores)
                if not k32.SetProcessAffinityMask(h, mask):
                    errors.append("CPU cores")
        finally:
            k32.CloseHandle(h)
    else:
        try:
            os.setpriority(os.PRIO_PROCESS, int(pid), _NICE.get(priority, 0))
        except (OSError, AttributeError):
            errors.append("priority")
        if cores:
            try:
                os.sched_setaffinity(int(pid), set(cores))
            except (OSError, AttributeError):
                errors.append("CPU cores")
    return ("couldn't set " + " and ".join(errors)) if errors else ""


def describe_cores(cores) -> str:
    cores = sorted({int(c) for c in (cores or [])})
    total = os.cpu_count() or 1
    if not cores or len(cores) >= total:
        return f"All {total} cores"
    ranges, start = [], None
    for i, c in enumerate(cores):
        if start is None:
            start = c
        if i == len(cores) - 1 or cores[i + 1] != c + 1:
            ranges.append(f"{start}" if start == c else f"{start}-{c}")
            start = None
    return f"Cores {', '.join(ranges)} ({len(cores)} of {total})"


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------
def default_server(index: int, existing: list) -> dict:
    used_ports = {s.get("port") for s in existing}
    used_rcon = {s.get("rcon_port") for s in existing}
    port, rcon = 7777, 27020
    while port in used_ports:
        port += 2
    while rcon in used_rcon:
        rcon += 1
    name = f"Server {index}"
    return {
        "id": secrets.token_hex(6),
        "name": name,
        "install_dir": os.path.join(BASE_DIR, "servers", safe_name(name)),
        "map": "TheIsland_WP",
        "session_name": f"My ARK Server {index}",
        "port": port,
        "rcon_port": rcon,
        "max_players": 70,
        "admin_password": secrets.token_urlsafe(9).replace("-", "x").replace("_", "y"),
        "server_password": "",
        "mods": "",
        "cluster": False,
        "battleye": False,
        "extra_options": "",
        "extra_args": "",
        "autostart": False,
        "update_on_start": False,
        "auto_restart_on_crash": True,
        "hide_log_window": True,
        "restart_times": "",
        "restart_warn_minutes": "15, 10, 5, 1",
        "update_on_scheduled_restart": True,
        "auto_update_restart": False,
        "backup_interval_min": 60,
        "backup_keep": 48,
        "auto_mod_update_restart": False,
        "mod_restart_wait_empty": False,
        "mod_restart_wait_minutes": 120,
        "ram_restart_gb": 0,
        "discord_notify": True,
        "timed_tasks": [],
        "upnp": False,
        "active_event": "",
        "passive_mods": "",
        "cmd_flags": ["-servergamelog"],
        "server_platform": "",
        "culture": "",
        "public_ip": "",
        "auto_public_ip": False,
        "multihome": "",
        "multihome_rcon": False,
        "cpu_priority": "Normal",
        "cpu_cores": [],
        "asaapi": False,
    }


# Copy to other servers: per-server settings that stay as they are on the server being copied to.
# Mods and timed tasks aren't Tamer settings here: mods have their own tick box, timed tasks their own copy button.
COPY_KEEP_SETTINGS = {"id", "name", "install_dir", "map", "session_name", "port", "rcon_port", "admin_password",
                      "server_password", "public_ip", "auto_public_ip", "multihome", "multihome_rcon", "upnp",
                      "cpu_cores", "autostart", "cluster", "asaapi", "mods", "passive_mods", "timed_tasks"}
# The same idea for the game's ini files. Lower case, and matched in any section.
COPY_KEEP_INI = {"sessionname", "port", "queryport", "rconport", "rconenabled", "multihome", "serveradminpassword",
                 "serverpassword", "spectatorpassword", "activemods", "altsavedirectoryname"}


def ini_merge_keep(source: str, target: str) -> str:
    """The text of `source`, but with the COPY_KEEP_INI lines taken from `target`."""
    def keep_key(line):
        key = line.split("=", 1)[0].strip().lower() if "=" in line else ""
        return key in COPY_KEEP_INI

    merged = "\n".join(line for line in source.splitlines() if not keep_key(line))
    section = None
    for line in target.splitlines():
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            section = st[1:-1]
        elif section and keep_key(line):
            key, value = line.split("=", 1)
            merged = ini_set(merged, section, key.strip(), value)
    return merged


# --------------------------------------------------------------------------------------
# Importing a server Tamer didn't make: from its launch line (running process or .bat), INI files and saves
# --------------------------------------------------------------------------------------
IMPORT_MAP_KEYS = {"sessionname": "session_name", "port": "port", "rconport": "rcon_port", "maxplayers": "max_players",
                   "serverpassword": "server_password", "serveradminpassword": "admin_password", "multihome": "multihome"}
IMPORT_MAP_DROP = {"listen", "rconenabled", "queryport"}  # Tamer adds these itself (QueryPort isn't used by ASA)
IMPORT_FLAG_KEYS = {"-serverplatform": "server_platform", "-culture": "culture", "-publicipforepic": "public_ip",
                    "-mods": "mods", "-passivemods": "passive_mods", "-activeevent": "active_event"}
IMPORT_FLAG_DROP = {"-port", "-winlivemaxplayers", "-multihome", "-nobattleye", "-clusterid", "-clusterdiroverride"}
SERVER_EXE_NAMES = ("arkascendedserver.exe", "asaapiloader.exe")


def split_cmdline(line: str) -> list:
    """Split a Windows command line the way Windows programs do (CommandLineToArgvW rules): spaces outside "quotes"
    separate arguments, the quotes themselves go, and \\" is a literal quote (2n backslashes + " = n backslashes and
    a quote that opens/closes; 2n+1 = n backslashes and a literal quote). Some launchers write the map line as
    "\\"TheIsland_WP\\"?SessionName=\\"My Server\\"...", which is why the values can still carry quotes."""
    args, cur, quoted, have, i = [], [], False, False, 0
    while i < len(line):
        ch = line[i]
        if ch == "\\":
            n = 0
            while i < len(line) and line[i] == "\\":
                n, i = n + 1, i + 1
            if i < len(line) and line[i] == '"':
                cur.append("\\" * (n // 2))
                if n % 2:
                    cur.append('"')  # escaped: a real quote character
                else:
                    quoted = not quoted
                i += 1
            else:
                cur.append("\\" * n)
            have = True
            continue
        if ch == '"':
            if quoted and line[i + 1:i + 2] == '"':  # "" inside quotes is a literal quote
                cur.append('"')
                i += 2
                continue
            quoted, have = not quoted, True
        elif ch in " \t" and not quoted:
            if have:
                args.append("".join(cur))
                cur, have = [], False
        else:
            cur.append(ch)
            have = True
        i += 1
    if have:
        args.append("".join(cur))
    return args


def split_cmdline_loose(line: str) -> list:
    """Split a launch line where \\" is used as an ordinary quote, e.g. TheIsland_WP?SessionName=\\"My Server\\"
    with no outer quotes (some managers write it like that, and ARK reads it that way). Backslashes right before
    a quote are dropped; quotes hold words together and are removed."""
    line = re.sub(r'\\+"', '"', line)
    return [t.replace('"', "") for t in re.findall(r'(?:[^\s"]+|"[^"]*"?)+', line.strip())]


def map_line_broken(args: list) -> bool:
    """True when the strict Windows split cut the map line apart: a value with an opening quote and no closing one
    (e.g. SessionName="JAG(Just), which means the launcher meant \\" as an ordinary quote."""
    at = next((i for i, a in enumerate(args) if os.path.basename(a).lower() in SERVER_EXE_NAMES), None)
    if at is None or at + 1 >= len(args) or args[at + 1].startswith("-"):
        return False
    return args[at + 1].count('"') % 2 == 1


def unquote(value: str) -> str:
    """A value with the quotes around it taken off: "My Server" -> My Server (quotes inside are kept)."""
    v = value.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def server_root_of(path: str):
    """The server's install folder from its exe path or any folder inside it, or None if it isn't one."""
    p = os.path.normpath(path)
    if os.path.basename(p).lower() in SERVER_EXE_NAMES:
        p = os.path.dirname(p)
    for _ in range(5):
        if os.path.isfile(os.path.join(p, SERVER_EXE_REL)):
            return p
        if os.path.dirname(p) == p:
            break
        p = os.path.dirname(p)
    return None


def parse_server_cmdline(line):
    """Tamer settings from an ARK launch line. Returns (settings, found) where found has "exe", "cluster_id",
    "cluster_dir", "asaapi" when they're in it. Unknown ?options and -flags are kept as extra options/arguments."""
    args = split_cmdline(line) if isinstance(line, str) else list(line)
    if isinstance(line, str) and map_line_broken(args):  # \" used as plain quotes: read it the way ARK does
        args = split_cmdline_loose(line)
    at = next((i for i, a in enumerate(args) if os.path.basename(a).lower() in SERVER_EXE_NAMES), None)
    found, s = {}, {}
    if at is None:
        return s, found
    found["exe"] = unquote(args[at])
    found["asaapi"] = os.path.basename(found["exe"]).lower() == "asaapiloader.exe"
    rest = args[at + 1:]
    known_flags = {f.lower(): f for _g, items in CMD_FLAG_GROUPS for f, _l, _h in items}
    extra_opts, extra_args, flags = [], [], []
    if rest and not rest[0].startswith("-"):
        parts = rest.pop(0).split("?")  # each part loses its own quotes below (the whole line's ends aren't a pair)
        s["map"] = unquote(parts[0])
        for p in parts[1:]:
            k, _, v = p.partition("=")
            key, v = k.strip().lower(), unquote(v)
            if key in IMPORT_MAP_KEYS and v:
                s[IMPORT_MAP_KEYS[key]] = v
            elif key not in IMPORT_MAP_DROP and p.strip():
                extra_opts.append(p.strip())
    s["battleye"] = True  # ASA runs BattlEye unless told -NoBattlEye
    for a in rest:
        k, eq, v = a.partition("=")
        key, v = k.lower(), unquote(v)
        if key == "-nobattleye":
            s["battleye"] = False
        elif key == "-port" and v and "port" not in s:
            s["port"] = v
        elif key == "-winlivemaxplayers" and v and "max_players" not in s:
            s["max_players"] = v
        elif key == "-clusterid":
            s["cluster"], found["cluster_id"] = True, v
        elif key == "-clusterdiroverride":
            found["cluster_dir"] = v
        elif key in IMPORT_FLAG_KEYS and eq:
            s[IMPORT_FLAG_KEYS[key]] = v
        elif key in IMPORT_FLAG_DROP:
            pass
        elif not eq and key in known_flags:
            flags.append(known_flags[key])
        elif a.startswith("-"):
            extra_args.append(f'{k}="{v}"' if eq and " " in v else a)
    for key in ("port", "rcon_port", "max_players"):
        if key in s:
            try:
                s[key] = int(s[key])
            except ValueError:
                del s[key]
    s["cmd_flags"] = flags
    s["extra_options"] = "?".join(extra_opts)
    s["extra_args"] = " ".join(extra_args)
    if "passive_mods" in s:  # Tamer keeps passive mods inside "mods" too
        mods = [m for m in s.get("mods", "").split(",") if m.strip()]
        s["mods"] = ",".join(mods + [m for m in s["passive_mods"].split(",") if m.strip() and m not in mods])
    return s, found


def bat_server_line(text: str, bat_dir: str):
    """The ARK launch line in a .bat file, with ^ line joins, `set` variables, %~dp0 and `cd` worked out."""
    text = re.sub(r"\^[ \t]*\r*\n", " ", text)  # ^ at the end of a line joins it to the next
    env, cwd = {"~dp0": bat_dir.rstrip("\\/") + os.sep}, bat_dir
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith(("rem ", "::", "@rem")):
            continue
        line = re.sub(r"%([^%\s]+)%", lambda m: env.get(m.group(1), env.get(m.group(1).lower(), m.group(0))), line)
        line = line.replace("%~dp0", env["~dp0"])
        m = re.match(r'(?i)^@?set\s+"?([^=\s"]+)=(.*?)"?$', line)
        if m:
            env[m.group(1)] = env[m.group(1).lower()] = m.group(2)
            continue
        m = re.match(r'(?i)^@?(?:cd|chdir|pushd)\s+(?:/d\s+)?"?([^"]+?)"?$', line)
        if m:
            cwd = os.path.join(cwd, m.group(1))
            continue
        m = re.search(r'(?i)("[^"]*(?:ArkAscendedServer|AsaApiLoader)\.exe"|\S*(?:ArkAscendedServer|AsaApiLoader)\.exe)', line)
        if m:
            exe = m.group(1).strip('"')
            if not os.path.isabs(exe):
                exe = os.path.normpath(os.path.join(cwd, exe))
            return f'"{exe}" ' + line[m.end():].strip()
    return None


def server_from_folder(root: str):
    """What the server folder itself says: GameUserSettings.ini values, ActiveMods, and the map from its saves."""
    s, notes = {}, []
    gus = read_text_file(os.path.join(root, CONFIG_REL, "GameUserSettings.ini"))
    for section, key, field in (("SessionSettings", "SessionName", "session_name"), ("SessionSettings", "Port", "port"),
                                ("ServerSettings", "RCONPort", "rcon_port"),
                                ("ServerSettings", "ServerAdminPassword", "admin_password"),
                                ("ServerSettings", "ServerPassword", "server_password"),
                                ("/Script/Engine.GameSession", "MaxPlayers", "max_players"),
                                ("ServerSettings", "ActiveMods", "mods")):
        v = ini_get(gus, section, key)
        if v:
            s[field] = int(v) if field in ("port", "rcon_port", "max_players") and v.isdigit() else v
    saves = os.path.join(root, SAVEDARKS_REL)
    maps = []
    if os.path.isdir(saves):
        for d in os.listdir(saves):
            full = os.path.join(saves, d)
            arks = [os.path.join(full, f) for f in os.listdir(full) if f.lower().endswith(".ark")] if os.path.isdir(full) else []
            if arks:
                maps.append((max(os.path.getmtime(a) for a in arks), d))
    if maps:
        s["map"] = max(maps)[1]
        notes.append(f"Map taken from the saves ({s['map']}).")
    return s, notes


def import_server(cfg, folder=None, cmdline=None, bat=None):
    """A new Tamer server for an existing ARK server. Pass its folder, its running command line, or a .bat path.
    Returns (server, found, notes); raises RuntimeError with a plain reason if it can't."""
    line, notes = cmdline, []
    if bat:
        line = bat_server_line(read_text_file(bat), os.path.dirname(os.path.abspath(bat)))
        if not line:
            raise RuntimeError("That .bat file doesn't start ArkAscendedServer.exe (or AsaApiLoader.exe).")
    from_line, found = parse_server_cmdline(line) if line else ({}, {})
    root = server_root_of(found.get("exe") or folder or "")
    if not root:
        raise RuntimeError("Couldn't find the server files (ShooterGame\\Binaries\\Win64\\ArkAscendedServer.exe) "
                           "there. Pick the server's main folder - the one with ShooterGame inside.")
    same = next((o for o in cfg.servers if os.path.normcase(os.path.normpath(o["install_dir"])) ==
                 os.path.normcase(root)), None)
    if same:
        raise RuntimeError(f"Tamer already manages that folder, as '{same['name']}'.")
    from_folder, folder_notes = server_from_folder(root)
    s = default_server(len(cfg.servers) + 1, cfg.servers)
    s.update(cmd_flags=[], install_dir=root)
    s.update(from_folder)
    s.update(from_line)  # the launch line wins: it's what the server actually runs with
    if "map" in from_line:
        folder_notes = [n for n in folder_notes if not n.startswith("Map taken")]
    if not from_line.get("map") and not from_folder.get("map"):
        notes.append("No map found - it's set to The Island. Change it on the Server tab if that's wrong.")
    s["name"] = s.get("session_name") or os.path.basename(root)
    s["asaapi"] = bool(found.get("asaapi"))
    if not s["asaapi"] and asaapi_status(s)["installed"]:
        notes.append("AsaApi is installed in this folder. If the server used plugins, tick 'Start this server with "
                     "AsaApi' on the Plugins tab.")
    notes += folder_notes
    if not line:
        notes.append("Read from the folder only (no launch line), so command-line options like mods or flags "
                     "may be missing - pick the running server or its .bat to get them.")
    clash = next((o for o in cfg.servers if o["port"] == s["port"] or o["rcon_port"] == s["rcon_port"]), None)
    if clash:
        notes.append(f"Its ports clash with '{clash['name']}' - change one of them before running both.")
    return s, found, notes


def servers_root(cfg) -> str:
    """Where new servers go: the folder picked in the welcome, else "servers" next to Tamer."""
    return cfg.data.get("servers_dir") or os.path.join(BASE_DIR, "servers")


def roomiest_drive():
    """(suggested servers folder, free GB) on the fixed drive with the most free space."""
    best = (os.path.expanduser("~"), 0.0)
    if IS_WINDOWS:
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        mask = k32.GetLogicalDrives()
        for i in range(26):
            root = f"{chr(65 + i)}:\\"
            if mask >> i & 1 and k32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED: no USB sticks, DVDs or network drives
                try:
                    free = shutil.disk_usage(root).free / 1024 ** 3
                except OSError:
                    continue
                if free > best[1]:
                    best = (os.path.join(root, "ARK Servers"), free)
    else:
        try:
            best = (os.path.join(best[0], "ARK Servers"), shutil.disk_usage(best[0]).free / 1024 ** 3)
        except OSError:
            pass
    return best


class AppConfig:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.first_run = not os.path.exists(path)  # no settings yet: the window shows the welcome
        self.data = {
            "steamcmd_dir": os.path.join(BASE_DIR, "steamcmd"),
            "backup_root": os.path.join(BASE_DIR, "backups"),
            "backup_copy_dir": "",
            "battlemetrics_token": "",
            "backup_before_update": True,
            "cluster_id": secrets.token_hex(8),
            "cluster_dir": os.path.join(BASE_DIR, "cluster"),
            "rcon_host": "127.0.0.1",
            "update_check_min": 30,
            "curseforge_api_key": "",
            "mod_cache": {},
            "mod_check_min": 30,
            "close_to_tray": True,
            "minimize_to_tray": False,
            "theme": "system",
            "stagger_starts": True,
            "discord_webhook": "",
            "discord_name": APP_NAME,
            "discord_events": {k: k != "players" for k, _ in DISCORD_EVENTS},
            "tamer_update_check": True,  # look for a newer Tamer on GitHub once a day
            "servers_dir": "",  # where new servers go ("" = servers next to Tamer); set by the welcome
            "servers": [],
        }
        self.lock = threading.RLock()
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data.update(loaded)
            except Exception as e:
                backup = self.path + ".corrupt"
                shutil.copy2(self.path, backup)
                print(f"Config unreadable ({e}); copied to {backup}")
        if self.data.get("discord_name") in ("ARK Server Manager", ""):  # pre-Tamer default
            self.data["discord_name"] = APP_NAME
        events = {k: k != "players" for k, _ in DISCORD_EVENTS}
        events.update(self.data.get("discord_events") or {})
        self.data["discord_events"] = events
        servers = []
        for s in self.data.get("servers", []):
            merged = default_server(1, [])
            merged.update(s)
            servers.append(merged)
        self.data["servers"] = servers
        if not servers and self.first_run:  # a brand-new Tamer gets a starter server for the welcome to fill in;
            self.data["servers"].append(default_server(1, []))  # an empty list someone made themselves stays empty
            self.save()

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)

    @property
    def servers(self) -> list:
        return self.data["servers"]

    def get(self, sid):
        return next((s for s in self.servers if s["id"] == sid), None)


# --------------------------------------------------------------------------------------
# Runtime state + manager (all non-UI logic; thread-safe enough for a desktop tool)
# --------------------------------------------------------------------------------------
TASK_KINDS = [("broadcast", "Broadcast (big on-screen message)"), ("chat", "Chat message"),
              ("command", "Admin command(s)")]
TASK_KIND_LABELS = dict(TASK_KINDS)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TASK_PLACEHOLDERS = "{server} {map} {players} {max_players} {time} {next_restart}"


def describe_task_schedule(task) -> str:
    if task.get("mode") == "interval":
        n = int(task.get("every_min") or 0)
        return f"Every {n // 60} h" if n >= 60 and n % 60 == 0 else f"Every {n} min"
    days = sorted(task.get("days") or range(7))
    when = "Daily" if len(days) == 7 else ", ".join(WEEKDAYS[d] for d in days)
    return f"{when} at {task.get('times', '')}"


def example_tasks():
    return [
        {"id": secrets.token_hex(4), "enabled": False, "kind": "broadcast", "mode": "interval", "every_min": 60,
         "times": "", "days": list(range(7)),
         "text": "Welcome to {server}! Join our Discord: discord.gg/yourinvite"},
        {"id": secrets.token_hex(4), "enabled": False, "kind": "chat", "mode": "interval", "every_min": 30,
         "times": "", "days": list(range(7)), "text": "{players}/{max_players} survivors online. Next restart: {next_restart}"},
        {"id": secrets.token_hex(4), "enabled": False, "kind": "command", "mode": "times", "every_min": 60,
         "times": "05:00", "days": [0], "text": "DestroyWildDinos"},
    ]


class ServerRuntime:
    def __init__(self, sid):
        self.sid = sid
        self.proc = None
        self.pid = None
        self.want_running = False
        self.state = "Stopped"
        self.busy = None
        self.op_lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.online = False
        self.players = []
        self.start_time = None
        self.last_poll = 0.0
        self.polling = False
        self.last_backup = time.time()
        self.restart_target = None
        self.countdown_until = None
        self.crash_times = collections.deque(maxlen=10)
        self.installed_build = None
        self.log = collections.deque(maxlen=3000)
        self.console = collections.deque(maxlen=2000)
        self.rcon = None
        self.rcon_key = None
        self.warned_not_online = False
        self.announced_online = False
        self.players_ready = False
        self.player_ids = {}
        self.cpu = None
        self.ram = None
        self.last_cpu = None
        self.ram_over = 0
        self.history = collections.deque(maxlen=720)  # (time, cpu %, ram bytes) every 5 s = 1 hour
        self.mod_files = None  # {mod id: file id} as loaded at server start
        self.mods_outdated = []
        self.mod_wait_since = None  # waiting for an empty server before a mod update restart
        self.mod_wait_names = ""
        self.queued = False
        self.auto_public_ip = ""
        self.stats_pid = None  # the real ArkAscendedServer.exe when started through AsaApiLoader
        self.hidden_windows = []  # ARK log windows Tamer hid, so they can be shown again
        self.mod_check_pending = False
        self.task_last = {}  # timed task id -> schedule bookkeeping (epoch)
        self.task_ran = {}  # timed task id -> when it last actually ran
        self.online_since_start = False


class Manager:
    def __init__(self, cfg: AppConfig, notify):
        self.cfg = cfg
        self.notify = notify  # notify(kind, sid, payload) - must be thread-safe
        self.rt: dict[str, ServerRuntime] = {}
        self.stop_event = threading.Event()
        self.window_lock = threading.Lock()  # _log_window runs from the tick and from a start's fast check
        self.steam_lock = threading.Lock()
        self.latest_build = None
        self.last_update_check = 0.0
        self.last_scan = 0.0
        self.first_tick = True
        self.start_queue = []
        self.start_queue_active = False
        self.start_queue_cancel = threading.Event()
        self.paused = False
        self.autostart_enabled = True
        self.service_mode = False
        self._log_lock = threading.Lock()
        self.cf = CurseForge(lambda: self.cfg.data.get("curseforge_api_key", ""))
        self.discord = DiscordNotifier(cfg, self._discord_error)
        self.last_mod_check = time.time()
        self.notified_build = None
        self.sys_mem = (0, 0)
        self.last_sys_alert = 0.0
        self._last_discord_error = 0.0

    def _discord_error(self, msg):
        if time.time() - self._last_discord_error > 300 and self.cfg.servers:  # don't flood the log
            self._last_discord_error = time.time()
            for s in self.cfg.servers:
                self.log(s, msg)

    def alert(self, s, event, title, desc="", color="info"):
        if s is not None and not s.get("discord_notify", True):
            return
        self.discord.send(event, s["name"] if s else None, title, desc, color)

    @staticmethod
    def mod_ids(s):
        return [m.strip() for m in s.get("mods", "").split(",") if m.strip()]

    # ---- basics -----------------------------------------------------------------
    def runtime(self, sid) -> ServerRuntime:
        if sid not in self.rt:
            self.rt[sid] = ServerRuntime(sid)
        return self.rt[sid]

    def log(self, s, msg: str):
        line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {'[service] ' if self.service_mode else ''}{msg}"
        sid = s["id"] if isinstance(s, dict) else s
        self.runtime(sid).log.append(line)
        self.notify("log", sid, line)
        srv = s if isinstance(s, dict) else self.cfg.get(sid)
        if srv:
            self._write_log_file(srv, line)

    @staticmethod
    def log_path(s):
        return os.path.join(LOG_DIR, f"{safe_name(s['name'])}_{s['id'][:4]}.log")

    def _write_log_file(self, s, line):
        path = self.log_path(s)
        try:
            with self._log_lock:
                os.makedirs(LOG_DIR, exist_ok=True)
                if os.path.exists(path) and os.path.getsize(path) > 5 * 1024 * 1024:
                    os.replace(path, path + ".1")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            pass

    def load_log_tail(self, s, n=400):
        rt = self.runtime(s["id"])
        if rt.log:
            return
        try:
            with open(self.log_path(s), "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()[-n:]
            rt.log.extend(lines)
        except OSError:
            pass

    def console(self, s, text: str):
        rt = self.runtime(s["id"])
        for line in text.splitlines() or [""]:
            rt.console.append(line)
        self.notify("console", s["id"], text)

    @staticmethod
    def exe_path(s):
        return os.path.join(s["install_dir"], SERVER_EXE_REL)

    @staticmethod
    def config_dir(s):
        return os.path.join(s["install_dir"], CONFIG_REL)

    def is_installed(self, s):
        return os.path.isfile(self.exe_path(s))

    def backup_dir(self, s):
        return os.path.join(self.cfg.data["backup_root"], safe_name(s["name"]) + "_" + s["id"][:4])

    def build_command(self, s, mask=False) -> list[str]:
        pw = "********" if mask else s["admin_password"]
        opts = [s["map"], "listen", f"SessionName={s['session_name']}", f"Port={s['port']}",
                f"RCONPort={s['rcon_port']}", "RCONEnabled=True", f"MaxPlayers={s['max_players']}"]
        if s.get("server_password"):
            opts.append(f"ServerPassword={'********' if mask else s['server_password']}")
        if s.get("multihome", "").strip():
            opts.append(f"MultiHome={s['multihome'].strip()}")
        for extra in s.get("extra_options", "").split("?"):
            if extra.strip():
                opts.append(extra.strip())
        opts.append(f"ServerAdminPassword={pw}")  # keep last
        args = [self.exe_path(s), "?".join(opts), f"-port={s['port']}",
                f"-WinLiveMaxPlayers={s['max_players']}"]
        if not s.get("battleye"):
            args.append("-NoBattlEye")
        if s.get("server_platform", "").strip():
            args.append(f"-ServerPlatform={s['server_platform'].strip()}")
        if s.get("culture", "").strip():
            args.append(f"-culture={s['culture'].strip()}")
        ip = (self.runtime(s["id"]).auto_public_ip if s.get("auto_public_ip") else "") or s.get("public_ip", "").strip()
        if ip:
            args.append(f"-PublicIPForEpic={ip}")
        if s.get("multihome", "").strip():
            args.append("-MultiHome")
        extra_lower = s.get("extra_args", "").lower()
        for flag, _l, _h in (x for _g, items in CMD_FLAG_GROUPS for x in items):
            if flag in s.get("cmd_flags", []) and flag.lower() not in extra_lower:
                args.append(flag)
        mod_list = [m.strip() for m in s.get("mods", "").split(",") if m.strip()]
        passive = [m for m in mod_list if m in {x.strip() for x in s.get("passive_mods", "").split(",")}]
        if mod_list:  # passive mods must also be in -mods, and listed first (Studio Wildcard's instructions)
            ordered = passive + [m for m in mod_list if m not in passive]
            args.append(f"-mods={','.join(ordered)}")
        if passive:
            args.append(f"-passivemods={','.join(passive)}")
        if s.get("active_event", "").strip():
            args.append(f"-ActiveEvent={s['active_event'].strip()}")
        if s.get("cluster"):
            args.append(f"-clusterid={self.cfg.data['cluster_id']}")
            args.append(f"-ClusterDirOverride={self.cfg.data['cluster_dir']}")
        if s.get("extra_args", "").strip():
            # Split on spaces outside "double quotes". Backslashes stay literal so Windows paths survive.
            args += [t.replace('"', "") for t in re.findall(r'(?:[^\s"]+|"[^"]*"?)+', s["extra_args"])]
        return args

    @staticmethod
    def to_cmdline(args: list[str]) -> str:
        """Windows command line in the form Unreal expects: -Key="value with spaces"."""
        parts = []
        for i, a in enumerate(args):
            if " " not in a:
                parts.append(a)
            elif i > 1 and a.startswith("-") and "=" in a:
                k, v = a.split("=", 1)
                parts.append(f'{k}="{v}"')
            else:
                parts.append(f'"{a}"')
        return " ".join(parts)

    # ---- RCON -----------------------------------------------------------------
    def rcon(self, s, cmd: str) -> str:
        rt = self.runtime(s["id"])
        host = s["multihome"].strip() if s.get("multihome_rcon") and s.get("multihome", "").strip() \
            else self.cfg.data.get("rcon_host", "127.0.0.1")
        key = (host, int(s["rcon_port"]), s["admin_password"])
        if rt.rcon is None or rt.rcon_key != key:
            if rt.rcon:
                rt.rcon.close()
            rt.rcon = RconClient(*key)
            rt.rcon_key = key
        return rt.rcon.command(cmd)

    def try_rcon(self, s, cmd: str):
        try:
            return self.rcon(s, cmd)
        except Exception as e:
            self.log(s, f"RCON '{cmd}' failed: {e}")
            return None

    def broadcast(self, s, msg: str):
        if self.runtime(s["id"]).online:
            self.try_rcon(s, f"Broadcast {msg}")
            self.try_rcon(s, f"ServerChat {msg}")

    # ---- process control --------------------------------------------------------
    def is_running(self, s) -> bool:
        rt = self.runtime(s["id"])
        if rt.proc is not None and rt.proc.poll() is None:
            return True
        return pid_alive(rt.pid)

    def adopt_processes(self):
        procs = scan_server_processes()
        for s in self.cfg.servers:
            rt = self.runtime(s["id"])
            if self.is_running(s):
                continue
            exe = os.path.normcase(os.path.normpath(self.exe_path(s)))
            for pid, path, cmdline in procs:
                if path and os.path.normcase(os.path.normpath(path)) == exe and (
                        f"Port={s['port']}" in cmdline or f"-port={s['port']}" in cmdline):
                    rt.pid, rt.proc, rt.want_running = pid, None, True
                    rt.stats_pid = None
                    self.apply_cpu(s, quiet=True)
                    rt.start_time = rt.start_time or time.time()
                    rt.announced_online = True  # it was already up; don't announce it again
                    rt.online_since_start = True
                    rt.players_ready = False
                    self.log(s, f"Found already-running server process (PID {pid}); now managing it.")
                    break

    def reset_for_handoff(self):
        """Called when this engine takes over from another (window <-> background service)."""
        for s in self.cfg.servers:
            rt = self.runtime(s["id"])
            if not self.is_running(s):
                rt.proc = rt.pid = None
            rt.want_running = False
            rt.restart_target = None
            rt.online = False
            rt.task_last = {}
            rt.last_backup = time.time()
            if self.is_running(s):
                rt.want_running = True
                rt.announced_online = True
                rt.players_ready = False
        self.adopt_processes()
        self.first_tick = False
        self.last_scan = time.time()

    def ports_in_use_by_other(self, s):
        for o in self.cfg.servers:
            if o["id"] != s["id"] and self.is_running(o) and (
                    o["port"] == s["port"] or o["rcon_port"] == s["rcon_port"]):
                return o
        return None

    def _start(self, s):
        rt = self.runtime(s["id"])
        if self.is_running(s):
            self.log(s, "Server is already running.")
            rt.want_running = True
            return
        if not self.is_installed(s):
            self.log(s, "Server files are not installed yet - use 'Install / Update' first.")
            return
        clash = self.ports_in_use_by_other(s)
        if clash:
            self.log(s, f"Port conflict with running server '{clash['name']}'. Change ports first.")
            return
        os.makedirs(self.config_dir(s), exist_ok=True)
        if s.get("auto_public_ip"):
            try:
                rt.auto_public_ip = public_ip()
                self.log(s, f"Public IP for the server list: {rt.auto_public_ip}")
            except Exception as e:
                self.log(s, f"Couldn't look up the public IP ({e}); using the saved one.")
        cmd = self.build_command(s)
        use_api = False
        if s.get("asaapi"):
            if asaapi_status(s)["installed"]:
                cmd[0] = asaapi_paths(s)["loader"]
                use_api = True
            else:
                self.log(s, "AsaApi is switched on but not installed - starting without plugins. "
                            "Install it on the Plugins tab.")
        rt.stats_pid = None
        self.log(s, ("Starting with AsaApi: " if use_api else "Starting: ")
                 + self.to_cmdline([cmd[0]] + self.build_command(s, mask=True)[1:]))
        popen_args = dict(cwd=os.path.dirname(self.exe_path(s)), stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        target = self.to_cmdline(cmd) if IS_WINDOWS else cmd
        try:  # break away from any job object so the server survives the manager/service exiting
            rt.proc = subprocess.Popen(target, creationflags=DETACHED_FLAGS | (0x01000000 if IS_WINDOWS else 0),
                                       **popen_args)
        except OSError:
            rt.proc = subprocess.Popen(target, creationflags=DETACHED_FLAGS, **popen_args)
        rt.pid = rt.proc.pid
        rt.want_running = True
        rt.online = False
        rt.warned_not_online = False
        rt.start_time = time.time()
        rt.last_backup = time.time()
        rt.announced_online = rt.players_ready = False
        rt.player_ids = {}
        rt.mod_files, rt.mods_outdated = None, []
        rt.mod_wait_since = None  # the new process loads the new mods, so there's nothing left to wait for
        rt.last_cpu, rt.ram_over = None, 0
        rt.history.clear()
        rt.task_last = {}
        rt.online_since_start = False
        rt.hidden_windows = []
        self.log(s, f"Process started (PID {rt.pid}). The map can take several minutes to load.")
        if IS_WINDOWS and hide_ark_log(s):
            threading.Thread(target=self._hide_log_window_soon, args=(s, rt.pid), daemon=True).start()
        if s.get("upnp"):
            threading.Thread(target=self._upnp_refresh, args=(s,), daemon=True).start()
        if use_api:
            threading.Thread(target=self._find_api_child, args=(s, rt.pid), daemon=True).start()
        else:
            self.apply_cpu(s)

    def _stop(self, s, graceful=True, announce=True):
        rt = self.runtime(s["id"])
        rt.want_running = False
        if not self.is_running(s):
            self.log(s, "Server is not running.")
            rt.proc = rt.pid = None
            return
        if graceful and rt.online:
            self.log(s, "Saving world...")
            self.try_rcon(s, "SaveWorld")
            time.sleep(5)
            self.log(s, "Sending DoExit...")
            self.try_rcon(s, "DoExit")
            deadline = time.time() + 180
            while time.time() < deadline and self.is_running(s):
                time.sleep(2)
        elif graceful:
            self.log(s, "RCON is not reachable, so the world can't be saved first; stopping process.")
        if self.is_running(s):
            self.log(s, "Process still running - forcing it to close.")
            kill_pid(rt.pid)
            time.sleep(3)
        rt.proc = rt.pid = None
        rt.online = False
        rt.players = []
        if rt.rcon:
            rt.rcon.close()
        rt.cpu = rt.ram = None
        rt.announced_online = False
        self.log(s, "Server stopped.")
        if announce:
            self.alert(s, "status", "Stopped", "The server was shut down.", "muted")

    def _countdown(self, s, target: dt.datetime, minutes: list[int], what: str) -> bool:
        """Broadcast warnings until `target`. Returns False if cancelled."""
        rt = self.runtime(s["id"])
        rt.countdown_until = target
        try:
            for m in sorted(minutes, reverse=True):
                at = target - dt.timedelta(minutes=m)
                wait = (at - dt.datetime.now()).total_seconds()
                if wait > 0 and rt.cancel_event.wait(wait):
                    self.log(s, f"{what} cancelled.")
                    self.broadcast(s, f"The scheduled {what.lower()} has been cancelled.")
                    return False
                if (dt.datetime.now() - at).total_seconds() < 45:
                    self.log(s, f"Warning players: {what.lower()} in {m} minute(s)")
                    self.broadcast(s, f"Server {what.lower()} in {m} minute{'s' if m != 1 else ''}. "
                                      f"Please get somewhere safe.")
            wait = (target - dt.datetime.now()).total_seconds()
            if wait > 0 and rt.cancel_event.wait(wait):
                self.log(s, f"{what} cancelled.")
                return False
            return True
        finally:
            rt.countdown_until = None

    # ---- operations (run in worker threads through run_op) ---------------------
    def run_op(self, s, label: str, fn, *args) -> bool:
        rt = self.runtime(s["id"])
        if not rt.op_lock.acquire(blocking=False):
            self.log(s, f"Can't run '{label}' - busy with '{rt.busy}'.")
            return False
        rt.busy = label
        rt.cancel_event.clear()
        self.notify("state", s["id"], None)

        def worker():
            try:
                fn(s, *args)
            except Exception as e:
                self.log(s, f"ERROR during {label}: {e}")
                self.log(s, traceback.format_exc().strip())
            finally:
                rt.busy = None
                rt.op_lock.release()
                self.notify("state", s["id"], None)

        threading.Thread(target=worker, daemon=True, name=f"{label}-{s['name']}").start()
        return True

    def op_start(self, s):
        if s.get("update_on_start") or not self.is_installed(s):
            if not self.is_installed(s):
                self.log(s, "Server not installed - installing first.")
            self._update(s, validate=False)
        self._start(s)

    def op_stop(self, s, warn_minutes=None):
        if warn_minutes and self.runtime(s["id"]).online:
            target = dt.datetime.now() + dt.timedelta(minutes=max(warn_minutes))
            self.alert(s, "restart", f"Shutting down at {target:%H:%M}", "Players are being warned in-game.", "warn")
            if not self._countdown(s, target, warn_minutes, "Shutdown"):
                return
        self._stop(s, graceful=True)

    def op_restart(self, s, update=False, warn_minutes=None, target=None, reason="Restart"):
        rt = self.runtime(s["id"])
        try:
            if warn_minutes and (rt.online or target):  # a scheduled time still gets warnings once players can join
                target = target or dt.datetime.now() + dt.timedelta(minutes=max(warn_minutes))
                self.log(s, f"{reason}: restarting at {target:%H:%M}.")
                self.alert(s, "restart", f"Restarting at {target:%H:%M}", f"Reason: {reason}", "warn")
                if not self._countdown(s, target, warn_minutes, "Restart"):
                    self.alert(s, "restart", "Restart cancelled", "", "muted")
                    return
            elif target:
                wait = (target - dt.datetime.now()).total_seconds()
                if wait > 0 and rt.cancel_event.wait(wait):
                    return
            was_running = self.is_running(s)
            if was_running:
                self.alert(s, "restart", "Restarting now", f"Reason: {reason}" + (" (updating game files)" if update else ""), "warn")
            self._stop(s, graceful=True, announce=not was_running)
            if update:
                try:
                    self._update(s, validate=False)
                except Exception as e:  # never leave the server down because an update failed
                    self.log(s, f"Game update failed ({e}) - starting the installed version instead.")
                    self.alert(s, "update", "Game update failed - starting current version", str(e), "bad")
            self._start(s)
        finally:
            rt.restart_target = None

    # ---- update all servers, one after another ----------------------------------
    def update_all(self, servers, warn=True, restart=True, wait_online=True, skip_current=True, validate=False,
                   progress=lambda s, status: None, cancel: threading.Event | None = None):
        """Update servers one at a time: warn -> stop -> SteamCMD -> start -> (wait until online) -> next.
        Servers that share an install folder are updated together. Returns {server id: final status}."""
        cancel = cancel or threading.Event()
        groups = collections.OrderedDict()
        for s in servers:
            groups.setdefault(os.path.normcase(os.path.normpath(s["install_dir"])), []).append(s)
        if skip_current:
            try:
                self.latest_build = self.fetch_latest_build()
            except Exception as e:
                self.log(servers[0], f"Update all: couldn't look up the latest build ({e}); updating everything.")
        results = {}

        def mark(group, status):
            for s in group:
                results[s["id"]] = status
                progress(s, status)

        updated = skipped = failed = 0
        for group in groups.values():
            if cancel.is_set():
                mark(group, "Cancelled")
                continue
            installed = [self.read_installed_build(s) for s in group]
            if skip_current and self.latest_build and all(b == self.latest_build for b in installed) \
                    and all(self.is_installed(s) for s in group):
                mark(group, f"Up to date (build {self.latest_build})")
                skipped += len(group)
                continue
            # take each server's operation lock (wait if something else is running on it)
            held = []
            try:
                for s in group:
                    rt = self.runtime(s["id"])
                    while not rt.op_lock.acquire(timeout=1):
                        progress(s, f"Waiting for '{rt.busy}' to finish")
                        if cancel.is_set():
                            break
                    else:
                        held.append(s)
                        rt.busy = "Updating (all)"
                        rt.cancel_event.clear()
                        continue
                    break
                if len(held) < len(group):
                    mark(group, "Cancelled")
                    continue
                self.notify("state", None, None)
                was_running = [s for s in group if self.is_running(s)]
                if warn and was_running:
                    online = [s for s in was_running if self.runtime(s["id"]).online]
                    stop_ok = True
                    threads, outcome = [], {}
                    for s in online:
                        try:
                            warns = parse_minutes(s.get("restart_warn_minutes", "")) or [5, 1]
                        except ValueError:
                            warns = [5, 1]
                        target = dt.datetime.now() + dt.timedelta(minutes=max(warns))
                        progress(s, f"Warning players - restarting at {target:%H:%M}")
                        self.alert(s, "restart", f"Restarting at {target:%H:%M} to update",
                                   "Part of 'Update all servers'.", "warn")
                        t = threading.Thread(target=lambda s=s, w=warns, tg=target: outcome.__setitem__(
                            s["id"], self._countdown(s, tg, w, "Restart")), daemon=True)
                        t.start()
                        threads.append(t)
                    for t in threads:
                        t.join()
                    stop_ok = all(outcome.values())
                    if not stop_ok or cancel.is_set():
                        mark(group, "Cancelled (servers left running)")
                        continue
                for s in was_running:
                    progress(s, "Stopping")
                    self._stop(s, graceful=True, announce=False)
                progress(group[0], "Updating") if len(group) == 1 else mark(group, "Updating")
                error = None
                try:
                    self._update(group[0], validate=validate)
                except Exception as e:
                    error = str(e)
                    self.log(group[0], f"Update all: update failed - {e}")
                for s in group:
                    self.runtime(s["id"]).installed_build = self.read_installed_build(s)
                if restart:
                    for s in was_running:
                        progress(s, "Starting")
                        self._start(s)
                    if wait_online:
                        deadline = time.time() + 30 * 60
                        pending = [s for s in was_running if self.is_running(s)]
                        while pending and time.time() < deadline and not cancel.is_set():
                            for s in pending:
                                progress(s, "Waiting for it to come back online "
                                            f"({format_duration(time.time() - (self.runtime(s['id']).start_time or time.time()))})")
                            time.sleep(3)
                            pending = [s for s in pending if self.is_running(s) and not self.runtime(s["id"]).online]
                        if pending and not cancel.is_set():
                            for s in pending:
                                self.log(s, "Update all: still not online after 30 minutes - moving on.")
                if error:
                    failed += len(group)
                    mark(group, f"Failed: {error}" + (" (started the old version)" if restart and was_running else ""))
                else:
                    updated += len(group)
                    builds = {self.runtime(s["id"]).installed_build for s in group}
                    mark(group, f"Done - build {', '.join(b for b in builds if b) or '?'}")
            finally:
                for s in held:
                    rt = self.runtime(s["id"])
                    rt.busy = None
                    rt.op_lock.release()
                self.notify("state", None, None)
        summary = f"{updated} updated, {skipped} already up to date, {failed} failed"
        if cancel.is_set():
            summary += ", the rest cancelled"
        self.log(servers[0], f"Update all finished: {summary}.")
        self.alert(None, "update", "Update all servers finished", summary + ".", "bad" if failed else "good")
        return results

    def op_update(self, s, validate=False):
        self._update(s, validate)

    def op_backup(self, s, reason="manual"):
        try:
            self._backup(s, reason)
        except Exception as e:
            self.alert(s, "backups", "Backup failed", str(e), "bad")
            raise

    def op_restore(self, s, path, restore_configs):
        self._restore(s, path, restore_configs)

    def auto_diagnose(self, s, reason):
        time.sleep(2)
        findings = diagnose_server(self, s)
        bad = [f for f in findings if f["severity"] in ("error", "warning")]
        for f in findings:
            if f["severity"] != "ok":
                self.log(s, f"Troubleshooter: {f['title']}. {f['fix']}")
        if bad:
            self.alert(s, "diagnose", reason, "\n".join(f"• {f['title']}" for f in bad[:5]) +
                       "\nOpen the manager and click Troubleshoot for details.", "bad")
        self.notify("diagnosis", s["id"], findings)

    def _crash_restart_when_free(self, s):
        rt = self.runtime(s["id"])
        deadline = time.time() + 60
        while rt.busy and time.time() < deadline:  # e.g. a cancelled countdown still unwinding
            time.sleep(0.5)
        if rt.want_running and not self.is_running(s):
            self.run_op(s, "Crash restart", self.op_crash_restart)

    def _find_api_child(self, s, loader_pid):
        """AsaApiLoader starts the real server as a child: find it for CPU settings and monitoring."""
        rt = self.runtime(s["id"])
        exe = os.path.normcase(os.path.normpath(self.exe_path(s)))
        deadline = time.time() + 120
        while time.time() < deadline and rt.pid == loader_pid and pid_alive(loader_pid):
            for pid, path, cmdline in scan_server_processes():
                if pid != loader_pid and path and os.path.normcase(os.path.normpath(path)) == exe and (
                        f"Port={s['port']}" in cmdline or f"-port={s['port']}" in cmdline):
                    rt.stats_pid = pid
                    self.log(s, f"AsaApi loaded the server (PID {pid}).")
                    self.apply_cpu(s)
                    return
            time.sleep(2)

    def apply_cpu(self, s, quiet=False, force=False):
        """Apply this server's CPU priority / core choice to its running process."""
        prio, cores = s.get("cpu_priority") or "Normal", s.get("cpu_cores") or []
        if prio == "Normal" and not cores and not force:
            return
        if force and not cores:
            cores = list(range(os.cpu_count() or 1))  # explicitly hand back every core
        rt = self.runtime(s["id"])
        err = apply_process_cpu(rt.stats_pid or rt.pid, prio, cores)
        if err:
            self.log(s, f"CPU settings: {err}.")
        elif not quiet:
            self.log(s, f"CPU priority {prio}, {describe_cores(cores)}.")

    # ---- start servers one at a time ------------------------------------------------
    def start_staggered(self, servers, reason="Start all"):
        """Queue servers to start one after another; each waits for the previous one to come online."""
        todo = [s for s in servers if not self.is_running(s)]
        if not todo:
            return
        if self.start_queue_active:
            for s in todo:  # add to the running queue
                if s["id"] not in [x["id"] for x in self.start_queue]:
                    self.start_queue.append(s)
                    self.runtime(s["id"]).queued = True
            return
        self.start_queue = list(todo)
        self.start_queue_cancel.clear()
        for s in todo:
            self.runtime(s["id"]).queued = True
        self.start_queue_active = True
        threading.Thread(target=self._start_queue_worker, args=(reason,), daemon=True, name="start-queue").start()

    def cancel_start_queue(self):
        self.start_queue_cancel.set()

    def _start_queue_worker(self, reason):
        try:
            while self.start_queue and not self.start_queue_cancel.is_set():
                s = self.start_queue.pop(0)
                rt = self.runtime(s["id"])
                rt.queued = False
                if self.is_running(s) or self.cfg.get(s["id"]) is None:
                    continue
                waiting_others = len(self.start_queue)
                self.log(s, f"{reason}: starting now" + (f" ({waiting_others} more queued after this one)."
                                                        if waiting_others else "."))
                deadline = time.time() + 60
                while not self.run_op(s, "Starting", self.op_start):  # busy with something else? wait a bit
                    if time.time() > deadline or self.start_queue_cancel.wait(2):
                        break
                time.sleep(3)
                deadline = time.time() + 30 * 60
                while time.time() < deadline and not self.start_queue_cancel.is_set():
                    if rt.online:
                        break
                    if not rt.busy and not self.is_running(s):  # failed to start / crashed while loading
                        self.log(s, f"{reason}: it didn't come up - moving on to the next server.")
                        break
                    self.start_queue_cancel.wait(3)
                else:
                    if not self.start_queue_cancel.is_set():
                        self.log(s, f"{reason}: still not online after 30 minutes - starting the next server anyway.")
        finally:
            for s in self.start_queue:
                self.runtime(s["id"]).queued = False
            if self.start_queue_cancel.is_set() and self.start_queue and self.cfg.servers:
                self.log(self.cfg.servers[0], f"{reason}: cancelled - {len(self.start_queue)} server(s) not started.")
            self.start_queue = []
            self.start_queue_active = False
            self.notify("state", None, None)

    # ---- cluster-wide broadcast -------------------------------------------------------
    def broadcast_all(self, message: str):
        """Send a broadcast (big on-screen message + chat) to every online server. Returns (sent, skipped)."""
        sent, skipped = [], []
        for s in self.cfg.servers:
            if not self.runtime(s["id"]).online:
                skipped.append(s["name"])
                continue
            ok = self.try_rcon(s, f"Broadcast {message}") is not None
            self.try_rcon(s, f"ServerChat {message}")
            (sent if ok else skipped).append(s["name"])
            if ok:
                self.log(s, f"Cluster broadcast: {message}")
        return sent, skipped

    # ---- wipe / fresh start -----------------------------------------------------------
    def map_save_dir(self, s):
        return os.path.join(s["install_dir"], SAVEDARKS_REL, s["map"])

    def op_wipe(self, s, mode, wipe_cluster=False, start_after=False):
        """mode: 'wild' (DestroyWildDinos), 'world' (map only, keep characters/tribes), 'all' (fresh world)."""
        if mode == "wild":
            out = self.rcon(s, "DestroyWildDinos")
            self.log(s, "Wipe: all wild creatures destroyed - they respawn fresh over the next few minutes.")
            self.alert(s, "status", "Wild creatures wiped", "They respawn fresh over the next few minutes.", "info")
            return out
        if self.is_running(s):
            self.log(s, "Wipe: stopping the server first.")
            self._stop(s, graceful=True, announce=False)
        backup = self._backup(s, "pre-wipe")  # always keep a way back
        if backup:
            self.log(s, f"Wipe: backup saved first ({os.path.basename(backup)}) - restore it to undo.")
        removed = 0
        mdir = self.map_save_dir(s)
        root = os.path.join(s["install_dir"], SAVEDARKS_REL)
        if os.path.isdir(mdir):
            for f in os.listdir(mdir):
                p = os.path.join(mdir, f)
                low = f.lower()
                if mode == "world" and not (low.endswith(".ark") or ".ark." in low):
                    continue  # keep .arkprofile / .arktribe (characters & tribes)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
                removed += 1
        elif os.path.isdir(root):  # older layout: saves directly in SavedArks
            for f in os.listdir(root):
                if f.lower().startswith(s["map"].lower()) and ".ark" in f.lower() and os.path.isfile(os.path.join(root, f)):
                    os.remove(os.path.join(root, f))
                    removed += 1
        what = "world (characters & tribes kept)" if mode == "world" else "world, characters and tribes"
        self.log(s, f"Wipe: removed {removed} file(s) - {what}.")
        if wipe_cluster:
            cdir = self.cfg.data["cluster_dir"]
            n = 0
            if os.path.isdir(cdir):
                for f in os.listdir(cdir):
                    p = os.path.join(cdir, f)
                    shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
                    n += 1
            self.log(s, f"Wipe: cluster transfer data cleared ({n} item(s)).")
        self.alert(s, "status", "Server wiped", f"Fresh start: {what}" + (" + cluster data" if wipe_cluster else "")
                   + ". A backup was taken first.", "warn")
        self.notify("backups", s["id"], None)
        if start_after:
            self._start(s)

    def op_crash_restart(self, s):
        time.sleep(5)
        self._start(s)

    # ---- SteamCMD -----------------------------------------------------------
    def steamcmd_exe(self):
        return os.path.join(self.cfg.data["steamcmd_dir"], "steamcmd.exe" if IS_WINDOWS else "steamcmd.sh")

    def ensure_steamcmd(self, s):
        exe = self.steamcmd_exe()
        if os.path.isfile(exe):
            return exe
        if not IS_WINDOWS:
            raise RuntimeError("SteamCMD auto-download is only supported on Windows.")
        d = self.cfg.data["steamcmd_dir"]
        os.makedirs(d, exist_ok=True)
        zpath = os.path.join(d, "steamcmd.zip")
        self.log(s, f"Downloading SteamCMD to {d} ...")
        req = urllib.request.Request(STEAMCMD_URL, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(d)
        os.remove(zpath)
        self.log(s, "SteamCMD downloaded.")
        return exe

    def _run_streamed(self, s, cmd) -> int:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        last_progress = 0.0
        for raw in iter(proc.stdout.readline, b""):
            for line in raw.decode("utf-8", "replace").replace("\r", "\n").split("\n"):
                line = line.strip()
                if not line:
                    continue
                if "progress:" in line and time.time() - last_progress < 4:
                    continue
                if "progress:" in line:
                    last_progress = time.time()
                self.log(s, "  " + line)
        return proc.wait()

    def _update(self, s, validate=False):
        rt = self.runtime(s["id"])
        old_build = self.read_installed_build(s)
        if self.is_running(s):
            raise RuntimeError("Stop the server before installing/updating.")
        install = os.path.normcase(os.path.normpath(s["install_dir"]))
        for o in self.cfg.servers:
            if o["id"] != s["id"] and self.is_running(o) and \
                    os.path.normcase(os.path.normpath(o["install_dir"])) == install:
                raise RuntimeError(f"'{o['name']}' runs from the same folder and is running - stop it first.")
        if self.cfg.data.get("backup_before_update", True) and os.path.isdir(
                os.path.join(s["install_dir"], SAVEDARKS_REL)):
            try:
                self._backup(s, "pre-update")
            except Exception as e:
                self.log(s, f"Pre-update backup failed: {e}")
                self.alert(s, "backups", "Pre-update backup failed", str(e), "bad")
        exe = self.ensure_steamcmd(s)
        os.makedirs(s["install_dir"], exist_ok=True)
        cmd = [exe, "+force_install_dir", s["install_dir"], "+login", "anonymous",
               "+app_update", str(ASA_APP_ID)] + (["validate"] if validate else []) + ["+quit"]
        with self.steam_lock:
            self.log(s, f"{'Validating' if validate else 'Installing/updating'} ARK server files in {s['install_dir']} "
                        f"(the first install is ~13 GB and can take a while)...")
            for attempt in range(1, 4):
                rc = self._run_streamed(s, cmd)
                if rc == 0 and self.is_installed(s):
                    break
                self.log(s, f"SteamCMD exited with code {rc}; retrying ({attempt}/3)...")
                time.sleep(3)
        rt.installed_build = self.read_installed_build(s)
        if self.is_installed(s):
            self.log(s, f"Server files ready (build {rt.installed_build or 'unknown'}).")
            if rt.installed_build and rt.installed_build != old_build:
                self.alert(s, "update", f"Game files updated to build {rt.installed_build}",
                           f"Previous build: {old_build or 'not installed'}", "info")
        else:
            raise RuntimeError("SteamCMD did not produce the server executable. See the log above.")

    @staticmethod
    def read_installed_build(s):
        acf = os.path.join(s["install_dir"], "steamapps", f"appmanifest_{ASA_APP_ID}.acf")
        m = re.search(r'"buildid"\s+"(\d+)"', read_text_file(acf))
        return m.group(1) if m else None

    @staticmethod
    def fetch_latest_build():
        req = urllib.request.Request(BUILD_API_URL, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        return str(data["data"][str(ASA_APP_ID)]["depots"]["branches"]["public"]["buildid"])

    def update_available(self, s):
        rt = self.runtime(s["id"])
        return bool(self.latest_build and rt.installed_build and self.latest_build != rt.installed_build)

    # ---- backups ------------------------------------------------------------
    def _backup(self, s, reason="manual"):
        rt = self.runtime(s["id"])
        arks = os.path.join(s["install_dir"], SAVEDARKS_REL)
        if not os.path.isdir(arks):
            self.log(s, "Nothing to back up yet (no SavedArks folder).")
            return None
        if rt.online:
            self.try_rcon(s, "SaveWorld")
            time.sleep(8)
        dest = self.backup_dir(s)
        os.makedirs(dest, exist_ok=True)
        name = f"{dt.datetime.now():%Y-%m-%d_%H-%M-%S}_{s['map']}_{reason}.zip"
        final = os.path.join(dest, name)
        tmp = final + ".partial"
        count, skipped = 0, 0
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for root, _dirs, files in os.walk(arks):
                for f in files:
                    if ARK_ROLLING_BACKUP_RE.search(f) or f.lower().endswith(".tmp"):
                        continue
                    full = os.path.join(root, f)
                    try:
                        z.write(full, os.path.join("SavedArks", os.path.relpath(full, arks)))
                        count += 1
                    except OSError:
                        skipped += 1
            for f in ("GameUserSettings.ini", "Game.ini"):
                p = os.path.join(self.config_dir(s), f)
                if os.path.isfile(p):
                    z.write(p, os.path.join("Config", "WindowsServer", f))
            cdir = self.cfg.data["cluster_dir"]
            if s.get("cluster") and os.path.isdir(cdir):
                for root, _dirs, files in os.walk(cdir):
                    for f in files:
                        full = os.path.join(root, f)
                        try:
                            z.write(full, os.path.join("Cluster", os.path.relpath(full, cdir)))
                        except OSError:
                            skipped += 1
        os.replace(tmp, final)
        rt.last_backup = time.time()
        self.log(s, f"Backup created: {name} ({human_size(os.path.getsize(final))}, {count} save files"
                    f"{f', {skipped} locked files skipped' if skipped else ''}).")
        self._copy_backup(s, final)
        self._prune_backups(s)
        self.notify("backups", s["id"], None)
        return final

    def backup_copy_dir(self, s):
        root = (self.cfg.data.get("backup_copy_dir") or "").strip()
        return os.path.join(root, os.path.basename(self.backup_dir(s))) if root else None

    def _copy_backup(self, s, path):
        dest = self.backup_copy_dir(s)
        if not dest:
            return
        try:
            os.makedirs(dest, exist_ok=True)
            target = os.path.join(dest, os.path.basename(path))
            shutil.copy2(path, target + ".partial")
            os.replace(target + ".partial", target)
            self.log(s, f"Backup copied to {dest}")
        except OSError as e:
            self.log(s, f"Couldn't copy the backup to {dest}: {e}")
            self.alert(s, "backups", "Backup copy failed", f"Couldn't copy to the second backup folder: {e}", "bad")

    @staticmethod
    def _zips(d):
        if not d or not os.path.isdir(d):
            return []
        items = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".zip")]
        return sorted(items, key=os.path.getmtime, reverse=True)

    def list_backups(self, s):
        """Newest first. Backups that only exist in the second copy folder are included too."""
        main = self._zips(self.backup_dir(s))
        names = {os.path.basename(p) for p in main}
        extra = [p for p in self._zips(self.backup_copy_dir(s)) if os.path.basename(p) not in names]
        return sorted(main + extra, key=os.path.getmtime, reverse=True)

    def _prune_backups(self, s):
        keep = int(s.get("backup_keep") or 0)
        if keep <= 0:
            return
        for d in (self.backup_dir(s), self.backup_copy_dir(s)):
            for old in self._zips(d)[keep:]:
                try:
                    os.remove(old)
                    self.log(s, f"Deleted old backup {old}")
                except OSError:
                    pass

    def _restore(self, s, path, restore_configs=True):
        if self.is_running(s):
            raise RuntimeError("Stop the server before restoring a backup.")
        saved = os.path.join(s["install_dir"], SAVED_REL)
        arks = os.path.join(s["install_dir"], SAVEDARKS_REL)
        stamp = f"{dt.datetime.now():%Y%m%d_%H%M%S}"
        with zipfile.ZipFile(path) as z:
            if os.path.isdir(arks):
                moved = f"{arks}_before_restore_{stamp}"
                os.rename(arks, moved)
                self.log(s, f"Current saves moved to {moved}")
            cfg_dir = self.config_dir(s)
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if name.endswith("/"):
                    continue
                if name.startswith("SavedArks/"):
                    target = os.path.join(saved, *name.split("/"))
                elif name.startswith("Config/WindowsServer/") and restore_configs:
                    target = os.path.join(cfg_dir, os.path.basename(name))
                    if os.path.isfile(target):
                        shutil.copy2(target, f"{target}.before_restore_{stamp}")
                else:
                    continue
                root = saved if name.startswith("SavedArks/") else cfg_dir
                if not os.path.abspath(target).startswith(os.path.abspath(root)):
                    continue  # zip-slip guard
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        self.log(s, f"Restored backup {os.path.basename(path)}.")

    # ---- monitor loop ----------------------------------------------------------
    def start_monitor(self):
        threading.Thread(target=self._monitor, daemon=True, name="monitor").start()

    def _monitor(self):
        while not self.stop_event.is_set():
            try:
                if not self.paused:
                    self._tick()
            except Exception:
                traceback.print_exc()
            self.notify("state", None, None)
            self.stop_event.wait(5)

    def _poll(self, s):
        rt = self.runtime(s["id"])
        try:
            out = self.rcon(s, "ListPlayers")
            if not rt.online:
                self.log(s, "Server is online (RCON responding).")
                rt.players_ready = False  # don't announce everyone after a reconnect
            rt.online = True
            rt.online_since_start = True
            rt.players = parse_players(out)
            if not rt.announced_online:
                rt.announced_online = True
                up = f" after {format_duration(time.time() - rt.start_time)}" if rt.start_time else ""
                self.alert(s, "status", "Online", f"{MAP_LABELS.get(s['map'], s['map'])} is up{up}. "
                                                  f"Build {rt.installed_build or '?'} · {len(rt.players)}/{s['max_players']} players · "
                                                  f"{len(self.mod_ids(s))} mod(s)", "good")
            if self.mod_ids(s) and rt.mod_files is None and not rt.mod_check_pending:
                rt.mod_check_pending = True
                threading.Thread(target=self.check_mod_updates, args=(s,), daemon=True).start()
            current = {pid: name for _n, name, pid in rt.players}
            if rt.players_ready:
                for pid, name in current.items():
                    if pid not in rt.player_ids:
                        self.log(s, f"Player joined: {name}")
                        self.alert(s, "players", f"{name} joined", f"{len(current)}/{s['max_players']} online", "good")
                for pid, name in rt.player_ids.items():
                    if pid not in current:
                        self.log(s, f"Player left: {name}")
                        self.alert(s, "players", f"{name} left", f"{len(current)}/{s['max_players']} online", "muted")
            rt.player_ids, rt.players_ready = current, True
            chat = self.rcon(s, "GetChat")
            lines = [ln for ln in chat.splitlines() if ln.strip() and NO_RESPONSE not in ln]
            if lines:
                self.console(s, "\n".join(f"[chat] {ln}" for ln in lines))
        except RconAuthError as e:
            if rt.online or not rt.warned_not_online:
                self.log(s, str(e))
                rt.warned_not_online = True
            rt.online = False
        except Exception:
            rt.online = False
        finally:
            rt.polling = False

    def _tick(self):
        now = time.time()
        if self.first_tick or now - self.last_scan > 60:
            self.last_scan = now
            self.adopt_processes()
            for s in self.cfg.servers:
                self.runtime(s["id"]).installed_build = self.read_installed_build(s)
        if self.first_tick:
            self.first_tick = False
            auto = [s for s in self.cfg.servers
                    if self.autostart_enabled and s.get("autostart") and not self.is_running(s)]
            if auto and self.cfg.data.get("stagger_starts", True) and len(auto) > 1:
                self.start_staggered(auto, "Auto-start")
            else:
                for s in auto:
                    self.log(s, "Auto-starting server.")
                    self.run_op(s, "Start", self.op_start)

        for s in list(self.cfg.servers):
            rt = self.runtime(s["id"])
            running = self.is_running(s)
            if running:
                if not rt.polling and now - rt.last_poll >= 10:
                    rt.last_poll, rt.polling = now, True
                    threading.Thread(target=self._poll, args=(s,), daemon=True).start()
                if not rt.online and rt.start_time and now - rt.start_time > 1200 and not rt.warned_not_online:
                    rt.warned_not_online = True
                    self.log(s, "Server has been starting for 20+ minutes without RCON responding - troubleshooting...")
                    threading.Thread(target=self.auto_diagnose, args=(s, "Stuck starting for 20+ minutes"),
                                     daemon=True).start()
            elif rt.proc is not None or rt.pid is not None:
                code = rt.proc.poll() if rt.proc is not None else None
                rt.proc = rt.pid = None
                rt.online, rt.players = False, []
                in_countdown = rt.busy and rt.countdown_until is not None
                if rt.want_running and not rt.online_since_start and not rt.busy:
                    threading.Thread(target=self.auto_diagnose, args=(s, "Crashed before it finished starting"),
                                     daemon=True).start()
                if rt.want_running and (not rt.busy or in_countdown):
                    if in_countdown:  # crashed while waiting to restart: don't sit out the countdown
                        rt.cancel_event.set()
                    self.log(s, f"Server process exited unexpectedly (exit code {code}).")
                    rt.crash_times.append(now)
                    recent = [t for t in rt.crash_times if now - t < 1800]
                    rt.announced_online = False
                    if not s.get("auto_restart_on_crash"):
                        rt.want_running = False
                        self.alert(s, "crash", "Crashed", f"Exit code {code}. Auto-restart is off for this server.", "bad")
                    elif len(recent) >= 5:
                        rt.want_running = False
                        self.log(s, "Crashed 5 times in 30 minutes - auto-restart paused. Check ShooterGame.log.")
                        self.alert(s, "crash", "Crashed repeatedly - auto-restart paused",
                                   "5 crashes in 30 minutes. Check ShooterGame.log on the host.", "bad")
                    else:
                        self.log(s, "Auto-restarting after crash...")
                        self.alert(s, "crash", "Crashed - restarting", f"Exit code {code}. Restarting automatically.", "bad")
                        threading.Thread(target=self._crash_restart_when_free, args=(s,), daemon=True).start()

            self._sample_resources(s, rt, running, now)
            self._log_window(s, rt, running)
            if running and rt.online and not rt.busy:
                self._run_due_tasks(s, rt, now)
            if running and rt.mod_wait_since is not None:
                self._mod_wait_check(s, rt)

            if rt.busy:
                rt.state = rt.busy
            elif running:
                rt.state = "Online" if rt.online else "Starting"
            else:
                rt.state = ("Queued to start" if rt.queued else "Stopped") if self.is_installed(s) else "Not installed"

            # scheduled restarts
            if running and rt.restart_target is None and not rt.busy and s.get("restart_times", "").strip():
                try:
                    times = parse_times(s["restart_times"])
                    warns = parse_minutes(s.get("restart_warn_minutes", "")) or []
                except ValueError:
                    times, warns = [], []
                if times:
                    nxt = next_occurrence(times, dt.datetime.now())
                    lead = (max(warns) if warns else 0) * 60 + 10
                    if (nxt - dt.datetime.now()).total_seconds() <= lead:
                        rt.restart_target = nxt
                        if not self.run_op(s, "Scheduled restart", self.op_restart,
                                           bool(s.get("update_on_scheduled_restart")), warns, nxt,
                                           "Scheduled restart"):
                            rt.restart_target = None

            # automatic backups
            interval = int(s.get("backup_interval_min") or 0)
            if interval > 0 and running and rt.online and not rt.busy and now - rt.last_backup >= interval * 60:
                self.run_op(s, "Backup", self.op_backup, "auto")

        # machine memory
        self.sys_mem = system_memory()
        used, total = self.sys_mem
        if total and used / total > 0.92 and now - self.last_sys_alert > 3600:
            self.last_sys_alert = now
            self.alert(None, "resources", "Host memory almost full",
                       f"{gb(used)} of {gb(total)} in use ({used / total:.0%}). Servers may crash or lag.", "warn")

        # mod update detection
        mod_min = int(self.cfg.data.get("mod_check_min") or 0)
        if mod_min > 0 and now - self.last_mod_check >= mod_min * 60:
            self.last_mod_check = now
            threading.Thread(target=self.check_mod_updates, daemon=True).start()

        # game update detection
        check_min = int(self.cfg.data.get("update_check_min") or 0)
        if check_min > 0 and now - self.last_update_check >= check_min * 60:
            self.last_update_check = now
            threading.Thread(target=self.check_updates, daemon=True).start()

    # ---- timed messages & commands -------------------------------------------------
    def _run_due_tasks(self, s, rt, now):
        nowdt = dt.datetime.fromtimestamp(now)
        for task in s.get("timed_tasks", []):
            if not task.get("enabled", True) or not task.get("text", "").strip():
                continue
            tid = task["id"]
            last = rt.task_last.get(tid)
            due = False
            if task.get("mode") == "interval":
                every = max(1, int(task.get("every_min") or 0)) * 60
                if last is None:
                    rt.task_last[tid] = now  # start counting once the server is online
                elif now - last >= every:
                    due = True
            else:
                days = task.get("days") or list(range(7))
                if nowdt.weekday() not in days:
                    continue
                try:
                    times = parse_times(task.get("times", ""))
                except ValueError:
                    continue
                for h, m in times:
                    at = nowdt.replace(hour=h, minute=m, second=0, microsecond=0)
                    if 0 <= (nowdt - at).total_seconds() < 90 and (last is None or last < at.timestamp()):
                        due = True
                        break
            if due:
                rt.task_last[tid] = now
                threading.Thread(target=self.run_task, args=(s, task), daemon=True).start()

    def task_text(self, s, text):
        rt = self.runtime(s["id"])
        nxt = "not scheduled"
        try:
            times = parse_times(s.get("restart_times", ""))
            if times:
                nxt = f"{next_occurrence(times, dt.datetime.now()):%H:%M}"
        except ValueError:
            pass
        values = {"server": s.get("session_name") or s["name"], "map": MAP_LABELS.get(s["map"], s["map"]),
                  "players": str(len(rt.players)), "max_players": str(s["max_players"]),
                  "time": f"{dt.datetime.now():%H:%M}", "next_restart": nxt}
        for k, v in values.items():
            text = text.replace("{" + k + "}", v)
        return text

    def run_task(self, s, task, manual=False):
        self.runtime(s["id"]).task_ran[task.get("id")] = time.time()
        text = self.task_text(s, task.get("text", "")).strip()
        kind = task.get("kind", "broadcast")
        if kind == "command":
            cmds = [c.strip() for c in text.splitlines() if c.strip()]
        else:
            msg = " ".join(line.strip() for line in text.splitlines() if line.strip())
            cmds = [("Broadcast " if kind == "broadcast" else "ServerChat ") + msg]
        for c in cmds:
            try:
                out = self.rcon(s, c)
                result = "" if not out or NO_RESPONSE in out else f" -> {out[:200]}"
                self.log(s, f"{'Manual' if manual else 'Timed'} task: {c}{result}")
            except Exception as e:
                self.log(s, f"Timed task '{c}' failed: {e}")
        self.notify("tasks", s["id"], None)

    def _upnp_refresh(self, s):
        try:
            res = upnp_open_port(s)
            self.log(s, f"UPnP: UDP {s['port']} forwarded to this PC." if res == "OK" else f"UPnP: {res}")
        except Exception as e:
            self.log(s, f"UPnP port forward failed: {e}")

    def _log_window(self, s, rt, running):
        """Hide ARK's log window while the setting is on; show the ones Tamer hid if it's switched off."""
        with self.window_lock:
            self._log_window_locked(s, rt, running)

    def _log_window_locked(self, s, rt, running):
        if not running:
            rt.hidden_windows = []
            return
        pids = [rt.pid, rt.stats_pid]
        if not hide_ark_log(s):
            # Show it again - including one hidden before Tamer last restarted, which it no longer remembers
            back = [h for h in set(rt.hidden_windows) | set(ark_log_windows(pids, hidden=True)) if show_window(h, True)]
            if back:
                self.log(s, "Showing ARK's log window: Tamer only hides it for servers started with AsaApi "
                            "(so there's always one window).")
            rt.hidden_windows = []
            return
        for hwnd in ark_log_windows(pids):
            if show_window(hwnd, False) and hwnd not in rt.hidden_windows:
                rt.hidden_windows.append(hwnd)
                self.log(s, "Hid ARK's log window (setting on the Server tab). The server log is on the Log tab.")

    def _hide_log_window_soon(self, s, pid):
        """Right after a start, look often so ARK's log window barely flashes up; the 5 s tick covers the rest."""
        rt = self.runtime(s["id"])
        deadline = time.time() + 180
        while time.time() < deadline and rt.pid == pid and pid_alive(pid) and not self.stop_event.is_set():
            self._log_window(s, rt, True)
            time.sleep(0.5)

    def _sample_resources(self, s, rt, running, now):
        if not running or not rt.pid:
            rt.cpu = rt.ram = None
            rt.last_cpu = None
            return
        st = process_stats(rt.stats_pid or rt.pid)
        if not st:
            return
        cpu_s, mem = st
        if cpu_s is not None:
            if rt.last_cpu and now > rt.last_cpu[0]:
                pct = (cpu_s - rt.last_cpu[1]) / (now - rt.last_cpu[0]) / (os.cpu_count() or 1) * 100
                rt.cpu = max(0.0, min(100.0, pct))
            rt.last_cpu = (now, cpu_s)
        rt.ram = mem
        rt.history.append((now, rt.cpu, mem))
        try:
            limit = float(s.get("ram_restart_gb") or 0)
        except (TypeError, ValueError):
            limit = 0
        if limit > 0 and mem and mem > limit * 1024 ** 3:
            rt.ram_over += 1
            if rt.ram_over == 6 and not rt.busy and rt.restart_target is None:  # ~30 s above the limit
                self.log(s, f"Memory use {gb(mem)} is above the {limit:g} GB limit - restarting.")
                self.alert(s, "resources", "High memory - restarting",
                           f"Using {gb(mem)}, limit is {limit:g} GB. Players are being warned.", "warn")
                warns = []
                try:
                    warns = parse_minutes(s.get("restart_warn_minutes", ""))
                except ValueError:
                    pass
                rt.restart_target = dt.datetime.now()
                if not self.run_op(s, "Memory restart", self.op_restart, False, warns, None, "High memory use"):
                    rt.restart_target = None
        else:
            rt.ram_over = 0

    def _mod_update_restart(self, s, rt, names, warn) -> bool:
        warns = []
        if warn:
            try:
                warns = parse_minutes(s.get("restart_warn_minutes", ""))
            except ValueError:
                pass
        rt.restart_target = dt.datetime.now()
        if not self.run_op(s, "Mod update restart", self.op_restart, False, warns, None, f"Mod update: {names}"):
            rt.restart_target = None
            return False
        self.alert(s, "update", "Mod update - restarting", names, "info")
        return True

    def _mod_wait_check(self, s, rt) -> bool:
        """Restart for a waiting mod update once the server is empty or the wait runs out. True if it restarted."""
        if not s.get("auto_mod_update_restart"):  # switched off while waiting: leave it to the user
            rt.mod_wait_since = None
            return False
        if rt.busy or rt.restart_target is not None:
            return False
        # rt.online goes False when a player check fails, so an unanswered check never counts as empty
        empty = rt.online and not rt.players
        limit = s.get("mod_restart_wait_minutes", 120)
        too_long = bool(limit) and time.time() - rt.mod_wait_since >= limit * 60
        if not (empty or too_long or not s.get("mod_restart_wait_empty")):
            return False
        if not self._mod_update_restart(s, rt, rt.mod_wait_names, not empty):
            return False
        rt.mod_wait_since = None
        return True

    def copy_settings_to(self, src, dst, mods=False, settings=False):
        """Copy the mod list and/or Tamer settings. Quick, in memory: the caller saves the config."""
        if mods:
            dst["mods"], dst["passive_mods"] = src.get("mods", ""), src.get("passive_mods", "")
        if settings:
            dst.update(json.loads(json.dumps({k: v for k, v in src.items() if k not in COPY_KEEP_SETTINGS})))

    def copy_game_settings_to(self, src, dst) -> str:
        """Copy the game's ini files, keeping dst's name, ports and passwords. Returns a note for the user."""
        src_dir, dst_dir = self.config_dir(src), self.config_dir(dst)
        if os.path.normcase(os.path.abspath(src_dir)) == os.path.normcase(os.path.abspath(dst_dir)):
            return "Game settings skipped: these servers share the same folder, so they already match."
        if self.is_running(dst):
            return "Game settings skipped: the server is running. Stop it and copy again."
        names = [f for f in (GUS, GINI) if os.path.isfile(os.path.join(src_dir, f))]
        if not names:
            return f"Game settings skipped: {src['name']} has no game settings files yet. Start it once to create them."
        os.makedirs(dst_dir, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        for f in names:
            path = os.path.join(dst_dir, f)
            target = ""
            if os.path.isfile(path):
                target = read_text_file(path)
                shutil.copy2(path, f"{path}.before-copy-{stamp}")
            write_text_file(path, ini_merge_keep(read_text_file(os.path.join(src_dir, f)), target))
        return "Game settings copied. The old files were saved next to the new ones."

    def check_mod_updates(self, only=None, manual=False):
        """Compare each running server's mods with CurseForge; restart or alert when a mod gets a new file."""
        servers = [s for s in self.cfg.servers if (only is None or s is only) and self.mod_ids(s)
                   and self.is_running(s) and self.runtime(s["id"]).online]
        if not servers:
            if manual:
                self.notify("info", None, "No running servers with mods to check.")
            return
        ids = sorted({i for s in servers for i in self.mod_ids(s)})
        try:
            mods = {m["id"]: m for m in self.cf.get_mods(ids)}
        except Exception as e:
            for s in servers:
                self.runtime(s["id"]).mod_check_pending = False
            self.log(servers[0], f"Mod update check failed: {e}")
            if manual:
                self.notify("error", None, f"Mod update check failed:\n{e}")
            return
        found = 0
        for s in servers:
            rt = self.runtime(s["id"])
            rt.mod_check_pending = False
            current = {i: mods[i]["file_id"] for i in self.mod_ids(s) if i in mods and mods[i].get("file_id")}
            if rt.mod_files is None:
                rt.mod_files = current
                self.log(s, f"Mod versions recorded for {len(current)} mod(s); watching for updates.")
                continue
            for i, f in current.items():
                rt.mod_files.setdefault(i, f)  # mods added since start: baseline them
            changed = [i for i, f in current.items() if rt.mod_files.get(i) != f and i not in rt.mods_outdated]
            if not changed:
                continue
            found += len(changed)
            rt.mods_outdated += changed
            names = ", ".join(mods[i]["name"] for i in changed)
            self.log(s, f"Mod update released: {names}")
            if s.get("auto_mod_update_restart") and not rt.busy and rt.restart_target is None:
                if s.get("mod_restart_wait_empty"):
                    first = rt.mod_wait_since is None
                    rt.mod_wait_names = f"{rt.mod_wait_names}, {names}" if not first else names
                    if first:
                        rt.mod_wait_since = time.time()
                    if not self._mod_wait_check(s, rt) and first:
                        self.log(s, "Mod update restart is waiting for the server to be empty.")
                        self.alert(s, "update", "Mod update - waiting for an empty server",
                                   f"{names}\nThe server will restart when nobody is online.", "info")
                else:
                    self._mod_update_restart(s, rt, names, True)
            else:
                self.alert(s, "update", "Mod update available", f"{names}\nRestart the server to load it.", "info")
        if manual:
            self.notify("info", None, f"Mod check done: {found} new mod update(s) found." if found else
                        "All installed mods are up to date (compared with the versions loaded at server start).")
        self.notify("state", None, None)

    def check_updates(self, manual=False):
        try:
            self.latest_build = self.fetch_latest_build()
        except Exception as e:
            if manual:
                self.notify("error", None, f"Could not check for updates:\n{e}")
            return
        if any(self.update_available(s) for s in self.cfg.servers) and self.notified_build != self.latest_build:
            self.notified_build = self.latest_build
            self.alert(None, "update", f"ARK server update released (build {self.latest_build})",
                       "Servers with auto-update enabled will restart to install it.", "info")
        for s in self.cfg.servers:
            rt = self.runtime(s["id"])
            rt.installed_build = self.read_installed_build(s)
            if self.update_available(s) and s.get("auto_update_restart") and self.is_running(s) \
                    and not rt.busy and rt.restart_target is None:
                warns = []
                try:
                    warns = parse_minutes(s.get("restart_warn_minutes", ""))
                except ValueError:
                    pass
                self.log(s, f"Game update available (build {self.latest_build}) - restarting to update.")
                rt.restart_target = dt.datetime.now()
                if not self.run_op(s, "Update restart", self.op_restart, True, warns, None, "Game update"):
                    rt.restart_target = None
        if manual:
            self.notify("info", None, f"Latest ARK: Survival Ascended server build: {self.latest_build}")
        self.notify("state", None, None)


# --------------------------------------------------------------------------------------
# Troubleshooting: read ShooterGame.log + check the PC for common startup problems
# --------------------------------------------------------------------------------------
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
# (regex, severity, title, how to fix) - {port}, {map} are filled in
LOG_PATTERNS = [
    (r"WSAEADDRINUSE|address already in use|Failed to bind|could not bind|bind\(\) failed", "error",
     "The game port is already in use",
     "Another program - or another copy of this server - is using port {port}. Close it, or change this "
     "server's game port on the Server tab."),
    (r"out of memory|OutOfMemory|Ran out of memory|Failed to allocate", "error", "The server ran out of memory",
     "ASA needs roughly 12-16 GB of RAM per map. Close other programs, run fewer maps at once, or set a "
     "memory-limit restart on the Automation tab."),
    (r"not enough space on the disk|No space left on device|disk (is )?full", "error", "The disk is full",
     "Free up space on the drive that holds the server and its backups."),
    (r"(Failed to load|Couldn't find|could not find|failed to find).{0,80}(/Game/Maps|_WP\b|map)", "error",
     "The map couldn't be loaded",
     "Check the map name '{map}' on the Server tab - it's case-sensitive. DLC maps (Astraeos, Lost Colony) "
     "and mod maps must be spelled exactly, and a mod map's mod must be in the mod list."),
    (r"(mod|curseforge).{0,80}(fail|error|invalid|not found|unable|corrupt)", "warning",
     "A mod had trouble downloading or loading",
     "Check the mod IDs on the Mods tab. Remove the most recently added mod and start again; the log lines "
     "below usually name the mod."),
    (r"Fatal error|Unhandled Exception|EXCEPTION_ACCESS_VIOLATION|Critical error", "error", "The server crashed",
     "Often a broken mod or a damaged update. Try 'Validate files', then remove recently added mods."),
    (r"(save|\.ark).{0,60}(corrupt|failed to load|unable to load)", "error", "The world save may be damaged",
     "Restore the newest backup from the Automation tab."),
    (r"battleye.{0,60}(fail|error)", "warning", "BattlEye failed to start",
     "Untick 'Enable BattlEye' on the Server tab unless you need it."),
    (r"LogEOS.{0,40}(Error|Fail)|EOS.{0,40}(login|auth).{0,40}(fail|error)", "warning",
     "Epic Online Services (the server list) reported errors",
     "The server may not appear in the in-game list. Check this PC's internet connection and that the "
     "Windows clock is synced (Settings > Time & language > Sync now)."),
]
LOG_READY_RE = re.compile(r"advertising for join", re.I)


def vc_runtime_installed():
    if not IS_WINDOWS:
        return True
    try:
        import winreg
        for path in (r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                     r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                    if winreg.QueryValueEx(k, "Installed")[0] == 1:
                        return True
            except OSError:
                continue
        return False
    except Exception:
        return True  # can't tell - don't raise a false alarm


def port_in_use(port: int, proto: str = "udp") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if proto == "udp" else socket.SOCK_STREAM)
    try:
        if IS_WINDOWS:
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0xFFFFFFFB), 1)
        s.bind(("0.0.0.0", int(port)))
        return False
    except OSError:
        return True
    finally:
        s.close()


def diagnose_server(mgr, s) -> list[dict]:
    """Return findings: dicts with severity (error/warning/info/ok), title, fix, evidence (list of log lines)."""
    out = []
    rt = mgr.runtime(s["id"])
    add = lambda sev, title, fix="", evidence=None: out.append(
        {"severity": sev, "title": title, "fix": fix, "evidence": evidence or []})
    running = mgr.is_running(s)
    fill = lambda t: t.replace("{port}", str(s["port"])).replace("{map}", s["map"])

    if not mgr.is_installed(s):
        add("error", "The server isn't installed", "Click 'Install' to download the server files with SteamCMD.")
        return out
    if not vc_runtime_installed():
        add("error", "The Microsoft Visual C++ runtime is missing",
            f"ASA's server needs it and quits immediately without it. Install it from {VC_REDIST_URL} "
            "then start the server again.")
    try:
        free = shutil.disk_usage(s["install_dir"]).free
        if free < 10 * 1024 ** 3:
            add("error", f"Only {gb(free)} free on the server's drive",
                "Updates need ~15 GB of headroom and saves can corrupt on a full disk. Free up space.")
        elif free < 30 * 1024 ** 3:
            add("warning", f"Low disk space: {gb(free)} free",
                "Updates and backups may fail soon. Consider freeing space or moving backups to another drive.")
    except OSError:
        pass
    used, total = system_memory()
    if total and total < 15 * 1024 ** 3:
        add("warning", f"This PC has {gb(total)} of RAM",
            "One ASA map usually needs 12-16 GB on its own. Expect lag or out-of-memory crashes with more maps or players.")
    elif total and not running and total - used < 8 * 1024 ** 3:
        add("warning", f"Only {gb(total - used)} of memory is free right now",
            "Close other programs (or other servers) before starting this one.")
    if not running:
        for port, proto, label in ((s["port"], "udp", "game"), (s["rcon_port"], "tcp", "RCON")):
            if port_in_use(port, proto):
                add("error", f"The {label} port {port} ({proto.upper()}) is already in use",
                    "Another program is using it - often another copy of the server. Close it or pick a different "
                    f"{label} port on the Server tab.")
    if s.get("asaapi"):
        st = asaapi_status(s)
        if not st["installed"]:
            add("error", "AsaApi is switched on but isn't installed",
                "Install it on the Plugins tab, or untick 'Start this server with AsaApi'.")
        hits = asaapi_log_findings(s)
        if hits:
            add("warning", "AsaApi logged errors",
                "A plugin may be broken or need updating - right after an ARK update, AsaApi and plugins often "
                "need updates too. Disable the plugin named below, or update AsaApi on the Plugins tab.", hits)
    if s["map"] not in MAP_IDS and not mgr.mod_ids(s):
        add("warning", f"'{s['map']}' isn't an official map name",
            "If it's a mod map, add the map's mod on the Mods tab; otherwise pick a map from the list.")

    # ShooterGame.log
    log_path = os.path.join(s["install_dir"], GAMELOG_REL)
    text = ""
    if os.path.isfile(log_path):
        try:
            with open(log_path, "rb") as f:
                f.seek(max(0, os.path.getsize(log_path) - 3 * 1024 * 1024))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            pass
        stale = rt.start_time and os.path.getmtime(log_path) < rt.start_time - 5
        if stale and not running:
            add("error", "The server stopped before writing a log",
                f"That usually means a missing Visual C++ runtime ({VC_REDIST_URL}), antivirus blocking "
                "ArkAscendedServer.exe, or damaged files - try 'Validate files'.")
            text = ""
    elif rt.start_time:
        add("error", "No ShooterGame.log was written",
            f"The server never got far enough to log. Check the Visual C++ runtime ({VC_REDIST_URL}), antivirus, "
            "and run 'Validate files'.")
    lines = text.splitlines()
    for pattern, sev, title, fix in LOG_PATTERNS:
        rx = re.compile(pattern, re.I)
        hits = [ln.strip()[:220] for ln in lines if rx.search(ln)]
        if hits:
            add(sev, title, fill(fix), hits[-3:])
    ready = any(LOG_READY_RE.search(ln) for ln in lines)
    if ready:
        add("ok", "The server finished starting and is advertising to the server list")
    if running and not rt.online:
        mins = (time.time() - rt.start_time) / 60 if rt.start_time else 0
        if ready:
            add("error", "The server is up, but RCON isn't answering",
                f"RCON port {s['rcon_port']} or the admin password may not match what the server uses. Check "
                "for a different ServerAdminPassword / RCONPort in GameUserSettings.ini, or a firewall blocking "
                "local connections.")
        else:
            add("info", f"Still starting ({mins:.0f} min so far)",
                "The first start - and any start that downloads mods - can take 10-20 minutes.")
    if rt.crash_times:
        recent = [t for t in rt.crash_times if time.time() - t < 3600]
        if recent:
            add("warning", f"{len(recent)} crash(es) in the last hour", "See the other findings for likely causes.")
    if not [f for f in out if f["severity"] in ("error", "warning")]:
        add("ok", "No problems found" if text else "No problems found (no log to check yet)")
    order = {"error": 0, "warning": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda f: order[f["severity"]])


def format_findings(s, findings) -> str:
    icon = {"error": "[PROBLEM]", "warning": "[WARNING]", "info": "[INFO]", "ok": "[OK]"}
    parts = [f"Troubleshooting report for {s['name']} ({dt.datetime.now():%Y-%m-%d %H:%M})", ""]
    for f in findings:
        parts.append(f"{icon[f['severity']]} {f['title']}")
        if f["fix"]:
            parts.append(f"    {f['fix']}")
        for e in f["evidence"]:
            parts.append(f"    log: {e}")
        parts.append("")
    return "\n".join(parts)


# --------------------------------------------------------------------------------------
# Connectivity: can players reach this server?
# --------------------------------------------------------------------------------------
IPIFY_URL = os.environ.get("ASM_IPIFY_URL", "https://api.ipify.org?format=json")
BATTLEMETRICS_URL = os.environ.get("ASM_BM_URL", "https://api.battlemetrics.com/servers")
BATTLEMETRICS_TOKEN_URL = "https://www.battlemetrics.com/developers"


def battlemetrics_search_url(name: str) -> str:
    return "https://www.battlemetrics.com/servers/arksa?" + urllib.parse.urlencode({"q": name, "sort": "rank"})


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packet is sent; picks the interface towards the internet
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def public_ip():
    req = urllib.request.Request(IPIFY_URL, headers={"User-Agent": f"Tamer/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["ip"]


def ip_kind(ip: str) -> str:
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid"
    if a in ipaddress.ip_network("100.64.0.0/10"):
        return "cgnat"
    return "private" if a.is_private else "public"


class BattleMetricsRefused(Exception):
    pass


def battlemetrics_lookup(name: str, token: str = ""):
    q = urllib.parse.urlencode({"filter[game]": "arksa", "filter[search]": name, "page[size]": 10})
    headers = {"User-Agent": f"Tamer/{APP_VERSION}", "Accept": "application/json"}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    req = urllib.request.Request(f"{BATTLEMETRICS_URL}?{q}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r).get("data", [])
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise BattleMetricsRefused("token rejected" if token.strip() else "token required")
        if e.code == 429:
            raise RuntimeError("BattleMetrics is rate-limiting requests - try again in a minute.")
        raise RuntimeError(f"BattleMetrics returned HTTP {e.code}.")
    out = []
    for d in data:
        a = d.get("attributes", {})
        out.append({"name": a.get("name", ""), "ip": a.get("ip", ""), "port": a.get("port"),
                    "players": a.get("players"), "max": a.get("maxPlayers"), "status": a.get("status", "")})
    return out


class UPnPError(Exception):
    def __init__(self, code, desc):
        super().__init__(f"router said: {desc or 'error'} ({code})")
        self.code = code


class UPnP:
    """Tiny UPnP Internet Gateway Device client (port mappings + external IP)."""
    SEARCH_TARGETS = ["urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                      "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
                      "urn:schemas-upnp-org:service:WANIPConnection:1"]

    def __init__(self):
        self.control_url = None
        self.service = None
        self.location = None

    def discover(self, timeout=3.0) -> bool:
        host, port = os.environ.get("ASM_SSDP_ADDR", "239.255.255.250:1900").rsplit(":", 1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        locations = []
        try:
            for st in self.SEARCH_TARGETS:
                msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                       f"MX: 2\r\nST: {st}\r\n\r\n").encode()
                sock.sendto(msg, (host, int(port)))
            end = time.time() + timeout
            while time.time() < end:
                try:
                    data, _ = sock.recvfrom(4096)
                except socket.timeout:
                    if locations:
                        break
                    continue
                for line in data.decode("utf-8", "replace").split("\r\n"):
                    if line.lower().startswith("location:"):
                        loc = line.split(":", 1)[1].strip()
                        if loc not in locations:
                            locations.append(loc)
        except OSError:
            pass
        finally:
            sock.close()
        for loc in locations:
            if self._parse(loc):
                return True
        return False

    def _parse(self, location) -> bool:
        import xml.etree.ElementTree as ET
        try:
            with urllib.request.urlopen(location, timeout=5) as r:
                root = ET.fromstring(r.read())
        except Exception:
            return False
        local = lambda el: el.tag.rsplit("}", 1)[-1]
        base = next((el.text for el in root.iter() if local(el) == "URLBase" and el.text), location)
        for el in root.iter():
            if local(el) != "service":
                continue
            fields = {local(c): (c.text or "").strip() for c in el}
            stype = fields.get("serviceType", "")
            if ("WANIPConnection" in stype or "WANPPPConnection" in stype) and fields.get("controlURL"):
                self.service = stype
                self.control_url = urllib.parse.urljoin(base, fields["controlURL"])
                self.location = location
                return True
        return False

    def _soap(self, action, args: dict) -> dict:
        import xml.etree.ElementTree as ET
        from xml.sax.saxutils import escape
        body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{self.service}">'
                + "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items()) +
                f"</u:{action}></s:Body></s:Envelope>")
        req = urllib.request.Request(self.control_url, data=body.encode("utf-8"), method="POST", headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{self.service}#{action}"'})
        local = lambda el: el.tag.rsplit("}", 1)[-1]
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                root = ET.fromstring(r.read())
        except urllib.error.HTTPError as e:
            try:
                root = ET.fromstring(e.read())
                code = next((el.text for el in root.iter() if local(el) == "errorCode"), str(e.code))
                desc = next((el.text for el in root.iter() if local(el) == "errorDescription"), "")
            except Exception:
                code, desc = str(e.code), ""
            raise UPnPError(code, desc)
        return {local(el): (el.text or "") for el in root.iter() if len(el) == 0}

    def external_ip(self):
        return self._soap("GetExternalIPAddress", {}).get("NewExternalIPAddress")

    def get_mapping(self, port, proto="UDP"):
        try:
            r = self._soap("GetSpecificPortMappingEntry",
                           {"NewRemoteHost": "", "NewExternalPort": port, "NewProtocol": proto})
            return r if r.get("NewInternalClient") else None
        except UPnPError as e:
            if e.code in ("714", "713", "402", "501"):
                return None
            raise

    def add_mapping(self, port, proto, client, desc):
        args = {"NewRemoteHost": "", "NewExternalPort": port, "NewProtocol": proto, "NewInternalPort": port,
                "NewInternalClient": client, "NewEnabled": 1, "NewPortMappingDescription": desc[:60],
                "NewLeaseDuration": 0}
        try:
            self._soap("AddPortMapping", args)
        except UPnPError:
            args["NewLeaseDuration"] = 604800  # some routers refuse permanent leases
            self._soap("AddPortMapping", args)


def firewall_rule_exists(s):
    if not IS_WINDOWS:
        return None
    name = f"ARK Ascended - {s['name']}".replace('"', "").replace("'", "")
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=20)
        return r.returncode == 0
    except Exception:
        return None


def check_connectivity(mgr, s) -> dict:
    """Walk server -> firewall -> router -> internet. Returns {"steps": [...], "verdict": str, "upnp": bool}."""
    steps = []
    add = lambda status, title, detail="": steps.append({"status": status, "title": title, "detail": detail})
    port = int(s["port"])
    rt = mgr.runtime(s["id"])
    running = mgr.is_running(s)
    if running and port_in_use(port, "udp"):
        add("ok", f"The server is running and listening on UDP {port}")
    elif running:
        add("warn", f"The server is running but UDP {port} isn't open yet", "It may still be loading the map.")
    else:
        add("fail", "The server isn't running", "Start it, then run this check again for a complete answer.")

    fw = firewall_rule_exists(s)
    if fw is True:
        add("ok", "Windows Firewall allows the game port")
    elif fw is False:
        add("warn", "No firewall rule from this manager",
            f"Click 'Open firewall port' (or allow ArkAscendedServer.exe / UDP {port} yourself). "
            "Ignore this if you already made your own rule.")

    lan = local_ip()
    try:
        pub = public_ip()
    except Exception as e:
        pub = None
        add("fail", "Couldn't find this network's public IP", f"Is the internet connection working? ({e})")
    if pub:
        add("ok" if ip_kind(lan) in ("private", "public") else "warn", f"This PC: {lan}  ·  Internet address: {pub}")

    upnp = UPnP()
    have_upnp = upnp.discover()
    mapped_ok = None
    if have_upnp:
        try:
            wan = upnp.external_ip()
        except Exception:
            wan = None
        kind = ip_kind(wan) if wan else None
        if kind in ("cgnat", "private"):
            add("fail", f"Your router doesn't have a public internet address ({wan})",
                "Your internet provider is sharing one address between customers (CGNAT), or there's a second "
                "router in front of yours. Port forwarding can't work like this. Ask your ISP for a public IP "
                "address, or put the other modem/router in bridge mode.")
        elif wan and pub and wan != pub:
            add("warn", f"The router reports {wan} but the internet sees {pub}",
                "There may be a second router or VPN in the way. Forward the port on that device too.")
        elif wan:
            add("ok", "The router has a public internet address")
        try:
            m = upnp.get_mapping(port, "UDP")
        except Exception as e:
            m, mapped_ok = None, None
            add("unknown", "Couldn't read the router's port forwards", str(e))
        else:
            if m and m.get("NewInternalClient") == lan:
                mapped_ok = True
                add("ok", f"The router forwards UDP {port} to this PC")
            elif m:
                mapped_ok = False
                add("fail", f"UDP {port} is forwarded to a different device ({m.get('NewInternalClient')})",
                    f"Change the forward to {lan}, or use 'Open port automatically'.")
            else:
                mapped_ok = False
                add("fail", f"The router isn't forwarding UDP {port} (as far as UPnP can see)",
                    "Click 'Open port automatically', or add a port forward in your router's settings: "
                    f"UDP {port} -> {lan}. Manual forwards don't always show up through UPnP.")
    else:
        add("unknown", "Couldn't talk to the router (UPnP is off or unsupported)",
            f"Can't check the port forward automatically. In your router's settings, forward UDP {port} to {lan}.")

    listed = None
    if rt.online:
        try:
            hits = battlemetrics_lookup(s["session_name"], mgr.cfg.data.get("battlemetrics_token", ""))
            mine = [h for h in hits if h["name"].strip().lower() == s["session_name"].strip().lower()]
            exact = [h for h in mine if (not pub or h["ip"] == pub)]
            if exact:
                h = exact[0]
                listed = True
                add("ok", "Your server is publicly listed (BattleMetrics)",
                    f"{h['name']} at {h['ip']}:{h['port']} - {h['players']}/{h['max']} players, {h['status']}.")
            elif mine:
                listed = False
                add("warn", "A server with this name is listed, but at a different address",
                    ", ".join(f"{h['ip']}:{h['port']}" for h in mine[:3]) + ". Give your server a more unique name.")
            else:
                add("unknown", "Not on the public BattleMetrics list yet",
                    "New servers can take 15-30 minutes to appear. If it never shows up, the server probably "
                    "can't register with the server list or isn't reachable.")
        except BattleMetricsRefused as e:
            if str(e) == "token rejected":
                add("unknown", "BattleMetrics rejected your API token",
                    "Check the BattleMetrics token in File > Settings > General (create a new one at "
                    f"{BATTLEMETRICS_TOKEN_URL}), or use 'Search BattleMetrics' to look in your browser.")
            else:
                add("unknown", "Public server list not checked (BattleMetrics needs a free token)",
                    "BattleMetrics no longer answers anonymous lookups. Add a free token in File > Settings > "
                    f"General (create one at {BATTLEMETRICS_TOKEN_URL}), or use 'Search BattleMetrics' to look "
                    "in your browser.")
        except Exception as e:
            add("unknown", "Couldn't check the public server list", str(e))

    statuses = [x["status"] for x in steps]
    # Listing alone proves nothing: ASA registers with the server list over an outbound connection,
    # so a server can be listed and still unreachable. Problems always win.
    if any(x["status"] == "fail" and "public internet address" in x["title"] for x in steps):
        verdict = "Players outside your home can't reach this server until the CGNAT / double-router issue is fixed."
    elif "fail" in statuses:
        verdict = "Something is blocking players - fix the items marked PROBLEM."
    elif listed and mapped_ok is not False:
        verdict = "Players should be able to find and join your server."
    elif mapped_ok:
        verdict = "Everything checked looks right. If friends still can't join, have them search the Unofficial list with 'Show player servers' ticked."
    else:
        verdict = "No blockers found, but the port forward couldn't be confirmed automatically."
    return {"steps": steps, "verdict": verdict, "upnp": have_upnp, "lan": lan}


def upnp_open_port(s) -> str:
    u = UPnP()
    if not u.discover():
        return "No UPnP router found. Turn on UPnP in your router's settings, or forward the port manually."
    lan = local_ip()
    u.add_mapping(int(s["port"]), "UDP", lan, f"ARK Ascended - {s['name']}")
    m = u.get_mapping(int(s["port"]), "UDP")
    if m and m.get("NewInternalClient") == lan:
        return "OK"
    return "The router accepted the request but the forward didn't show up. Forward the port manually."


# --------------------------------------------------------------------------------------
# AsaApi (ArkServerApi) - server plugin framework
#   Win64\AsaApiLoader.exe       starts ArkAscendedServer.exe with the API injected (and lives as long as it)
#   Win64\ArkApi\AsaApi.dll      the API itself
#   Win64\ArkApi\Plugins\<Name>\<Name>.dll (+ PluginInfo.json, config.json)
#   Win64\config.json            AsaApi settings      Win64\logs\ArkApi_<pid>.log   API logs
# --------------------------------------------------------------------------------------
ASAAPI_REPO = "ArkServerApi/AsaApi"
ASAAPI_RELEASE_API = os.environ.get("ASM_ASAAPI_API", f"https://api.github.com/repos/{ASAAPI_REPO}/releases/latest")
ASAAPI_SITE = "https://ark-server-api.com/resources/"
ASAAPI_RELEASES_PAGE = f"https://github.com/{ASAAPI_REPO}/releases"


def asaapi_paths(s):
    win64 = os.path.dirname(os.path.join(s["install_dir"], SERVER_EXE_REL))
    api = os.path.join(win64, "ArkApi")
    return {"win64": win64, "loader": os.path.join(win64, "AsaApiLoader.exe"), "api_dir": api,
            "dll": os.path.join(api, "AsaApi.dll"), "plugins": os.path.join(api, "Plugins"),
            "disabled": os.path.join(api, "Plugins_disabled"), "manifest": os.path.join(api, ".tamer_asaapi.json"),
            "config": os.path.join(win64, "config.json"), "logs": os.path.join(win64, "logs")}


def asaapi_status(s) -> dict:
    p = asaapi_paths(s)
    manifest = read_json_file(p["manifest"]) or {}
    installed = os.path.isfile(p["loader"]) and os.path.isfile(p["dll"])
    return {"installed": installed, "version": manifest.get("version") if installed else None,
            "manual": installed and not manifest, "loader": os.path.isfile(p["loader"]), "dll": os.path.isfile(p["dll"])}


def version_tuple(v) -> tuple:
    """"v1.15.3" or "1.15.3" -> (1, 15, 3). Anything that isn't a number counts as 0."""
    return tuple(int(p) if p.isdigit() else 0 for p in str(v).strip().lstrip("vV").split("."))


def tamer_latest() -> dict:
    """The newest Tamer release on GitHub: version, installer download (None if the release has none), notes, page."""
    req = urllib.request.Request(TAMER_RELEASE_API, headers={"User-Agent": f"Tamer/{APP_VERSION}",
                                                              "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError("No Tamer releases have been published yet.")
        if e.code in (403, 429):
            raise RuntimeError("GitHub is limiting update checks right now - try again in an hour.")
        raise RuntimeError(f"GitHub returned HTTP {e.code}.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach GitHub: {e.reason}")
    setup = next((a for a in rel.get("assets", []) if re.fullmatch(r"Tamer-Setup-[\d.]+\.exe", a.get("name", ""))), None)
    return {"version": str(rel.get("tag_name", "")).lstrip("vV"), "notes": (rel.get("body") or "").strip(),
            "page": rel.get("html_url") or TAMER_RELEASES_PAGE,
            "url": setup and setup.get("browser_download_url"), "name": setup and setup.get("name")}


def plain_notes(text: str) -> str:
    """GitHub release notes (Markdown) as plain text for a message box: no **bold**, `code` or [links](...)."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # [text](url) -> text
    text = re.sub(r"(\*\*|__|`)", "", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)  # headings
    return re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.M)  # bullets


def update_log(msg: str):
    """A line in manager_data\\logs\\update.log, so a failed self-update can be traced afterwards."""
    try:
        os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
        with open(os.path.join(DATA_DIR, "logs", "update.log"), "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def clean_child_env() -> dict:
    """This process's environment without the PyInstaller bookkeeping (_PYI_*, _MEIPASS*), for starting a program
    that may itself start Tamer.exe. Left in, they make the next Tamer.exe look for this one's unpacked files, which
    are gone once this copy exits: "Failed to load Python DLL ... _MEIxxxx\\python3xx.dll"."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI_", "_MEIPASS"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # PyInstaller 6.9+: the next one starts fresh whatever it inherits
    return env


def tamer_installed_copy() -> bool:
    """True when this is the installer's copy of Tamer.exe, so running a newer installer updates this very copy.
    (A Tamer.exe somewhere else, or tamer.py, would get a second, separate install instead.)"""
    return getattr(sys, "frozen", False) and os.path.isfile(os.path.join(BASE_DIR, "unins000.exe"))


def asaapi_latest():
    """(tag, zip download url, asset name) of the newest AsaApi release on GitHub."""
    req = urllib.request.Request(ASAAPI_RELEASE_API, headers={"User-Agent": f"Tamer/{APP_VERSION}",
                                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RuntimeError("GitHub is rate-limiting update checks right now - try again in an hour, or "
                               f"download AsaApi from {ASAAPI_RELEASES_PAGE} and use 'Install from .zip'.")
        raise RuntimeError(f"GitHub returned HTTP {e.code}.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach GitHub: {e.reason}")
    zips = [a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".zip")]
    zips.sort(key=lambda a: ("asaapi" not in a["name"].lower(), "pdb" in a["name"].lower(), a["name"]))
    if not zips:
        raise RuntimeError(f"The latest release ({rel.get('tag_name')}) has no .zip download. "
                           f"Get it from {ASAAPI_RELEASES_PAGE} and use 'Install from .zip'.")
    return rel.get("tag_name") or rel.get("name") or "?", zips[0]["browser_download_url"], zips[0]["name"]


def _zip_members(z):
    return [(i, i.filename.replace("\\", "/")) for i in z.infolist() if not i.filename.endswith(("/", "\\"))]


def _safe_target(root, rel):
    target = os.path.normpath(os.path.join(root, *[x for x in rel.split("/") if x not in ("", ".", "..")]))
    if not target.startswith(os.path.normpath(root) + os.sep):
        raise RuntimeError(f"Unsafe path in zip: {rel}")
    return target


def asaapi_install_zip(s, zip_path, version, log=print):
    """Extract an AsaApi release zip into Win64. Keeps your config.json and plugins."""
    p = asaapi_paths(s)
    if not os.path.isdir(p["win64"]):
        raise RuntimeError("Install the server first - the AsaApi goes into its Binaries\\Win64 folder.")
    with zipfile.ZipFile(zip_path) as z:
        members = _zip_members(z)
        names = [n for _i, n in members]
        root = None
        for n in names:  # where does the release keep its files? (zips may nest them in a folder)
            low = n.lower()
            if low.endswith("asaapiloader.exe"):
                root = n[: -len("asaapiloader.exe")]
                break
            if low.endswith("arkapi/asaapi.dll"):
                root = n[: -len("arkapi/asaapi.dll")]
                break
        if root is None:
            raise RuntimeError("That zip doesn't look like AsaApi (no AsaApiLoader.exe or ArkApi/AsaApi.dll inside).")
        written, kept = [], []
        for info, n in members:
            if not n.startswith(root):
                continue
            rel = n[len(root):]
            if not rel:
                continue
            target = _safe_target(p["win64"], rel)
            rel_low = rel.lower()
            if rel_low.startswith("arkapi/plugins/") and os.path.exists(target):
                kept.append(rel)
                continue  # never overwrite installed plugins
            if rel_low == "config.json" and os.path.exists(target):
                target = target + ".default"  # keep the user's settings; ship the new defaults alongside
                kept.append("config.json")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target + ".partial", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(target + ".partial", target)
            written.append(os.path.relpath(target, p["win64"]).replace("\\", "/"))
    os.makedirs(p["plugins"], exist_ok=True)
    old = read_json_file(p["manifest"]) or {}
    files = sorted(set(old.get("files", [])) | set(written))
    write_json_file(p["manifest"], {"version": version, "installed": time.time(), "files": files})
    log(f"AsaApi {version} installed ({len(written)} files)" + (f"; kept your {', '.join(sorted(set(kept)))[:120]}" if kept else "") + ".")
    return version


def asaapi_remove(s, log=print):
    """Remove AsaApi's own files. Plugins and your config.json stay (so a reinstall picks them up again)."""
    p = asaapi_paths(s)
    manifest = read_json_file(p["manifest"]) or {}
    files = manifest.get("files") or ["AsaApiLoader.exe", "ArkApi/AsaApi.dll"]
    removed = 0
    for rel in files:
        if rel.lower().startswith("arkapi/plugins") or rel.lower() == "config.json":
            continue
        target = os.path.join(p["win64"], *rel.split("/"))
        if os.path.isfile(target):
            os.remove(target)
            removed += 1
    if os.path.exists(p["manifest"]):
        os.remove(p["manifest"])
    log(f"AsaApi removed ({removed} files). Your plugins and config.json were kept.")


def list_plugins(s):
    p = asaapi_paths(s)
    out = []
    for enabled, folder in ((True, p["plugins"]), (False, p["disabled"])):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder), key=str.lower):
            d = os.path.join(folder, name)
            if not os.path.isdir(d):
                continue
            info = read_json_file(os.path.join(d, "PluginInfo.json")) or {}
            out.append({"name": name, "enabled": enabled, "dir": d,
                        "has_dll": os.path.isfile(os.path.join(d, name + ".dll")),
                        "has_config": os.path.isfile(os.path.join(d, "config.json")),
                        "full_name": info.get("FullName") or name, "version": info.get("Version", ""),
                        "description": info.get("Description", ""), "min_api": info.get("MinApiVersion", "")})
    return out


def install_plugin_zip(s, zip_path, log=print):
    """Install one or more plugins from a zip. Returns their names. Keeps existing config.json files."""
    p = asaapi_paths(s)
    os.makedirs(p["plugins"], exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        members = _zip_members(z)
        roots = {}  # prefix -> plugin name
        for _i, n in members:  # a plugin is a folder named like its .dll
            parts = n.split("/")
            if n.lower().endswith(".dll") and len(parts) >= 2 and parts[-2].lower() == parts[-1][:-4].lower():
                roots["/".join(parts[:-1]) + "/"] = parts[-2]
        if not roots:  # loose files: name the plugin after its main .dll
            dlls = [n for _i, n in members if n.lower().endswith(".dll")]
            if not dlls:
                raise RuntimeError("No plugin .dll found in that zip.")
            stem = os.path.splitext(os.path.basename(zip_path))[0].lower()
            main = next((d for d in dlls if os.path.basename(d)[:-4].lower() == stem), dlls[0])
            prefix = main[: len(main) - len(os.path.basename(main))]
            roots[prefix] = os.path.basename(main)[:-4]
        installed = []
        for prefix, name in roots.items():
            dest = os.path.join(p["disabled"], name) if os.path.isdir(os.path.join(p["disabled"], name)) \
                else os.path.join(p["plugins"], name)
            os.makedirs(dest, exist_ok=True)
            kept = False
            for info, n in members:
                if not n.startswith(prefix):
                    continue
                rel = n[len(prefix):]
                if not rel or "/" in rel and roots.get(prefix + rel.split("/")[0] + "/"):
                    continue
                target = _safe_target(dest, rel)
                if os.path.basename(rel).lower() == "config.json" and os.path.exists(target):
                    kept = True
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            log(f"Plugin {name} installed" + (" (kept your config.json)" if kept else "") + ".")
            installed.append(name)
    return installed


def set_plugin_enabled(s, name, enabled):
    p = asaapi_paths(s)
    src = os.path.join(p["disabled"] if enabled else p["plugins"], name)
    dst = os.path.join(p["plugins"] if enabled else p["disabled"], name)
    if not os.path.isdir(src):
        return
    if os.path.exists(dst):
        raise RuntimeError(f"Both an enabled and a disabled copy of {name} exist - remove one first.")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.rename(src, dst)


def asaapi_log_findings(s):
    """Recent AsaApi log errors: list of lines."""
    d = asaapi_paths(s)["logs"]
    if not os.path.isdir(d):
        return []
    logs = sorted((os.path.join(d, f) for f in os.listdir(d) if f.lower().startswith("arkapi")),
                  key=os.path.getmtime, reverse=True)
    if not logs:
        return []
    lines = read_text_file(logs[0]).splitlines()
    rx = re.compile(r"\[(error|critical)\]|failed to load|requires newer api|does not exist|exception", re.I)
    return [ln.strip()[:220] for ln in lines if rx.search(ln)][-5:]


# --------------------------------------------------------------------------------------
# Background service (headless mode run by Windows Task Scheduler) + window handoff
# --------------------------------------------------------------------------------------
SERVICE_TASK_NAME = "Tamer"
LEGACY_TASK_NAMES = ["ARK Ascended Server Manager"]  # before the rename
SERVICE_INFO_PATH = os.path.join(DATA_DIR, "service.json")
GUI_LOCK_PATH = os.path.join(DATA_DIR, "gui.lock")
LOG_DIR = os.path.join(DATA_DIR, "logs")


def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json_file(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def gui_lock_owner():
    """PID of a running manager window (other than this process), or None."""
    info = read_json_file(GUI_LOCK_PATH)
    pid = (info or {}).get("pid")
    return pid if pid and pid != os.getpid() and pid_alive(pid) else None


def service_info():
    """service.json of a live background service, or None."""
    info = read_json_file(SERVICE_INFO_PATH)
    if info and info.get("pid") != os.getpid() and pid_alive(info.get("pid")):
        return info
    return None


class LineSocket:
    """JSON-lines over a TCP socket, with timeouts that don't corrupt the stream."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def send(self, obj):
        self.sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def recv(self, timeout=None):
        self.sock.settimeout(timeout)
        while b"\n" not in self.buf:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def service_request(cmd: dict, timeout=5.0):
    """Open a connection to the background service and send one command. Returns (LineSocket, info) or None."""
    info = service_info()
    if not info:
        return None
    try:
        sock = socket.create_connection(("127.0.0.1", int(info["port"])), timeout=timeout)
    except OSError:
        return None
    ls = LineSocket(sock)
    ls.send(dict(cmd, token=info.get("token")))
    return ls, info


class ServiceAgent:
    """Runs the Manager without a window. Pauses itself whenever the manager window is open."""

    def __init__(self, mgr: "Manager"):
        self.mgr = mgr
        self.token = secrets.token_hex(16)
        self.takeover_until = 0.0
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        write_json_file(SERVICE_INFO_PATH, {"pid": os.getpid(), "port": self.srv.getsockname()[1],
                                            "token": self.token, "started": time.time()})

    def log_all(self, msg):
        for s in self.mgr.cfg.servers:
            self.mgr.log(s, msg)

    def busy_list(self):
        out = []
        for s in self.mgr.cfg.servers:
            rt = self.mgr.runtime(s["id"])
            if rt.busy:
                extra = f" (countdown to {rt.countdown_until:%H:%M})" if rt.countdown_until else ""
                out.append(f"{s['name']}: {rt.busy}{extra}")
        return out

    def window_active(self):
        return gui_lock_owner() is not None or time.time() < self.takeover_until

    def run(self):
        threading.Thread(target=self._accept_loop, daemon=True, name="service-control").start()
        self.mgr.paused = self.window_active()
        self.log_all("Background service started" + (" (paused - the manager window is open)." if self.mgr.paused else "."))
        self.mgr.start_monitor()
        while not self.mgr.stop_event.is_set():
            active = self.window_active()
            if active and not self.mgr.paused:
                self.mgr.paused = True
                self.log_all("Manager window opened - background service paused.")
            elif not active and self.mgr.paused:
                self.resume()
            self.mgr.stop_event.wait(2)

    def resume(self):
        self.mgr.cfg.load()
        self.mgr.reset_for_handoff()
        self.mgr.paused = False
        self.log_all("Manager window closed - background service took over.")

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        ls = LineSocket(conn)
        try:
            msg = ls.recv(10)
            if not msg or msg.get("token") != self.token:
                return
            cmd = msg.get("cmd")
            if cmd == "status":
                ls.send({"pid": os.getpid(), "paused": self.mgr.paused, "busy": self.busy_list(),
                         "servers": [{"name": s["name"], "state": self.mgr.runtime(s["id"]).state}
                                     for s in self.mgr.cfg.servers]})
            elif cmd in ("takeover", "shutdown"):
                self.takeover_until = time.time() + 120
                if not self.mgr.paused:
                    self.mgr.paused = True
                    self.log_all("Manager window opened - background service paused." if cmd == "takeover"
                                 else "Shutdown requested - finishing running jobs.")
                while True:
                    busy = self.busy_list()
                    if not busy:
                        break
                    ls.send({"status": "waiting", "busy": busy})
                    reply = ls.recv(2)
                    if reply and reply.get("cmd") == "cancel":
                        for s in self.mgr.cfg.servers:
                            self.mgr.runtime(s["id"]).cancel_event.set()
                ls.send({"status": "ready"})
                self.takeover_until = time.time() + 15  # the window's lock file keeps us paused from here on
                if cmd == "shutdown":
                    self.log_all("Background service stopping.")
                    try:
                        os.remove(SERVICE_INFO_PATH)
                    except OSError:
                        pass
                    time.sleep(0.5)
                    os._exit(0)
        except (OSError, ValueError, ConnectionError):
            pass
        finally:
            ls.close()


def run_service():
    os.makedirs(DATA_DIR, exist_ok=True)
    if service_info():
        return  # another service instance is already running
    cfg = AppConfig()
    mgr = Manager(cfg, lambda *a, **k: None)
    mgr.service_mode = True
    ServiceAgent(mgr).run()


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def service_launch_command():
    if getattr(sys, "frozen", False):
        return sys.executable, "--service"
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    return (pyw if os.path.exists(pyw) else py), f'"{os.path.abspath(__file__)}" --service'


def installed_task_name():
    """Name of the installed background-service task (current or pre-rename), or None."""
    if not IS_WINDOWS:
        return None
    for name in [SERVICE_TASK_NAME] + LEGACY_TASK_NAMES:
        try:
            r = subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True,
                               creationflags=CREATE_NO_WINDOW, timeout=20)
            if r.returncode == 0:
                return name
        except Exception:
            pass
    return None


def service_installed() -> bool:
    return installed_task_name() is not None


def _unregister_all_tasks_ps() -> str:
    return "\n".join(f"  Get-ScheduledTask -TaskName {_ps_quote(n)} -ErrorAction SilentlyContinue | "
                     "Unregister-ScheduledTask -Confirm:$false"
                     for n in [SERVICE_TASK_NAME] + LEGACY_TASK_NAMES)


def run_elevated_powershell(script: str, timeout=180) -> str:
    """Run a PowerShell script with an admin (UAC) prompt. Returns 'OK' or an error message."""
    os.makedirs(DATA_DIR, exist_ok=True)
    ps1 = os.path.join(DATA_DIR, "service_setup.ps1")
    result = os.path.join(DATA_DIR, "service_setup.result")
    if os.path.exists(result):
        os.remove(result)
    body = ("$ErrorActionPreference = 'Stop'\ntry {\n" + script +
            f"\n  'OK' | Out-File -Encoding ascii {_ps_quote(result)}\n}} catch {{\n"
            f"  $_.Exception.Message | Out-File -Encoding ascii {_ps_quote(result)}\n}}\n")
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(body)
    launcher = (f"Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
                f"'-NoProfile','-ExecutionPolicy','Bypass','-File',{_ps_quote(chr(34) + ps1 + chr(34))}")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", launcher], creationflags=CREATE_NO_WINDOW,
                       timeout=timeout, capture_output=True)
    except subprocess.TimeoutExpired:
        return "Timed out waiting for the admin prompt."
    if not os.path.exists(result):
        return "The admin prompt was cancelled."
    return read_text_file(result).strip() or "Unknown result"


def install_service() -> str:
    exe, args = service_launch_command()
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    script = f"""
  $a = New-ScheduledTaskAction -Execute {_ps_quote(exe)} -Argument {_ps_quote(args)} -WorkingDirectory {_ps_quote(BASE_DIR)}
  $t = New-ScheduledTaskTrigger -AtStartup
  $p = New-ScheduledTaskPrincipal -UserId {_ps_quote(user)} -LogonType S4U -RunLevel Limited
{_unregister_all_tasks_ps()}
  $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName {_ps_quote(SERVICE_TASK_NAME)} -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
  Start-ScheduledTask -TaskName {_ps_quote(SERVICE_TASK_NAME)}"""
    return run_elevated_powershell(script)


def uninstall_service() -> str:
    req = service_request({"cmd": "shutdown"})
    if req:
        ls, _ = req
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                msg = ls.recv(5)
                if msg and msg.get("status") == "ready":
                    break
        except (OSError, ConnectionError, ValueError):
            pass
        ls.close()
        time.sleep(1)
    return run_elevated_powershell(_unregister_all_tasks_ps())


def start_service_task() -> bool:
    try:
        r = subprocess.run(["schtasks", "/Run", "/TN", installed_task_name() or SERVICE_TASK_NAME], capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


# --------------------------------------------------------------------------------------
# System tray icon (Windows, pure ctypes)
# --------------------------------------------------------------------------------------
class TrayIcon:
    WM_TRAY = 0x0400 + 77
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10

    def __init__(self, tooltip, on_open, on_exit):
        self.tooltip, self.on_open, self.on_exit = tooltip, on_open, on_exit
        self.ok = False
        self.hwnd = None
        self._taskbar_created = None  # messages arrive during CreateWindowExW, before setup finishes
        self.ready = threading.Event()
        if IS_WINDOWS:
            threading.Thread(target=self._run, daemon=True, name="tray").start()
            self.ready.wait(5)

    def _run(self):
        try:
            self._loop()
        except Exception:
            traceback.print_exc()
        finally:
            self.ready.set()

    def _loop(self):
        import ctypes
        from ctypes import wintypes as w
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        s32 = ctypes.WinDLL("shell32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                        ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                        ("lpszClassName", w.LPCWSTR)]

        class GUID(ctypes.Structure):
            _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                        ("d4", ctypes.c_ubyte * 8)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                        ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", ctypes.c_wchar * 128),
                        ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", ctypes.c_wchar * 256),
                        ("uVersion", w.UINT), ("szInfoTitle", ctypes.c_wchar * 64), ("dwInfoFlags", w.DWORD),
                        ("guidItem", GUID), ("hBalloonIcon", w.HICON)]

        u32.DefWindowProcW.restype = LRESULT
        u32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        u32.RegisterClassW.restype = w.ATOM
        u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        u32.CreateWindowExW.restype = w.HWND
        u32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        u32.LoadIconW.restype = w.HICON
        u32.LoadIconW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
        u32.GetMessageW.restype = ctypes.c_int
        u32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        u32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
        u32.DispatchMessageW.restype = LRESULT
        u32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
        u32.CreatePopupMenu.restype = w.HMENU
        u32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
        u32.TrackPopupMenu.restype = ctypes.c_int
        u32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND,
                                       ctypes.c_void_p]
        u32.DestroyMenu.argtypes = [w.HMENU]
        u32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
        u32.SetForegroundWindow.argtypes = [w.HWND]
        u32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        u32.DestroyWindow.argtypes = [w.HWND]
        u32.PostQuitMessage.argtypes = [ctypes.c_int]
        u32.RegisterWindowMessageW.restype = w.UINT
        u32.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
        k32.GetModuleHandleW.restype = w.HMODULE
        k32.GetModuleHandleW.argtypes = [w.LPCWSTR]
        s32.ExtractIconW.restype = w.HICON
        s32.ExtractIconW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT]
        s32.Shell_NotifyIconW.restype = w.BOOL
        s32.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        self._u32, self._s32, self._ctypes = u32, s32, ctypes

        hinst = k32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wndproc)  # keep a reference or it gets garbage-collected
        cls = WNDCLASSW()
        cls.lpfnWndProc = self._wndproc_ref
        cls.hInstance = hinst
        cls.lpszClassName = "TamerTrayWindow"
        u32.RegisterClassW(ctypes.byref(cls))
        self.hwnd = u32.CreateWindowExW(0, cls.lpszClassName, "Tamer tray", 0, 0, 0, 0, 0,
                                        None, None, hinst, None)
        if not self.hwnd:
            return
        u32.LoadImageW.restype = w.HANDLE
        u32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
        icon = None
        if os.path.isfile(ICON_ICO):  # IMAGE_ICON, small-icon size, LR_LOADFROMFILE
            icon = u32.LoadImageW(None, ICON_ICO, 1, 16, 16, 0x10)
        if not icon:
            icon = s32.ExtractIconW(hinst, sys.executable, 0)
        if not icon or icon == 1:
            icon = u32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = icon
        nid.szTip = self.tooltip[:127]
        self._nid = nid
        self._taskbar_created = u32.RegisterWindowMessageW("TaskbarCreated")
        self.ok = bool(s32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid)))
        self.ready.set()
        msg = w.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        u32, s32, ctypes = self._u32, self._s32, self._ctypes
        try:
            if msg == self.WM_TRAY:
                event = lparam & 0xFFFF
                if event in (0x0202, 0x0203):  # left click / double click
                    self.on_open()
                elif event == 0x0205:  # right button up
                    self._menu(hwnd)
                return 0
            if self._taskbar_created and msg == self._taskbar_created:  # Explorer restarted -> re-add the icon
                s32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(self._nid))
                return 0
            if msg == 0x0010:  # WM_CLOSE
                s32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._nid))
                u32.DestroyWindow(hwnd)
                return 0
            if msg == 0x0002:  # WM_DESTROY
                u32.PostQuitMessage(0)
                return 0
        except Exception:
            traceback.print_exc()
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self, hwnd):
        u32, ctypes = self._u32, self._ctypes
        from ctypes import wintypes as w
        menu = u32.CreatePopupMenu()
        u32.AppendMenuW(menu, 0, 1, f"Open {APP_NAME}")
        u32.AppendMenuW(menu, 0x800, 0, None)  # separator
        u32.AppendMenuW(menu, 0, 2, "Exit")
        pt = w.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        u32.SetForegroundWindow(hwnd)
        cmd = u32.TrackPopupMenu(menu, 0x0100 | 0x0002 | 0x0020, pt.x, pt.y, 0, hwnd, None)  # RETURNCMD|RIGHTBUTTON|BOTTOMALIGN
        u32.PostMessageW(hwnd, 0, 0, 0)
        u32.DestroyMenu(menu)
        if cmd == 1:
            self.on_open()
        elif cmd == 2:
            self.on_exit()

    def balloon(self, title, text):
        if not self.ok:
            return
        try:
            nid = self._nid
            nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP | self.NIF_INFO
            nid.szInfoTitle = title[:63]
            nid.szInfo = text[:255]
            nid.dwInfoFlags = 0x1  # NIIF_INFO
            self._s32.Shell_NotifyIconW(self.NIM_MODIFY, self._ctypes.byref(nid))
            nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        except Exception:
            pass

    def remove(self):
        if self.hwnd and self.ok:
            try:
                self._u32.PostMessageW(self.hwnd, 0x0010, 0, 0)
                time.sleep(0.2)  # let the icon disappear before the process exits
            except Exception:
                pass
        self.ok = False


# --------------------------------------------------------------------------------------
# Windows "start with Windows" helper
# --------------------------------------------------------------------------------------
def startup_script_path():
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", f"{APP_NAME}.bat")


LEGACY_STARTUP_NAMES = ["ARK Ascended Server Manager.bat"]


def startup_enabled() -> bool:
    folder = os.path.dirname(startup_script_path())
    return any(os.path.exists(os.path.join(folder, n)) for n in [f"{APP_NAME}.bat"] + LEGACY_STARTUP_NAMES)


def set_start_with_windows(enabled: bool):
    path = startup_script_path()
    for legacy in LEGACY_STARTUP_NAMES:  # tidy up the pre-rename entry
        old = os.path.join(os.path.dirname(path), legacy)
        if os.path.exists(old):
            os.remove(old)
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    if getattr(sys, "frozen", False):
        launch = f'start "" "{sys.executable}"'
    else:
        py = sys.executable
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        launch = f'start "" "{pyw if os.path.exists(pyw) else py}" "{os.path.abspath(__file__)}"'
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'@echo off\r\ncd /d "{BASE_DIR}"\r\n{launch}\r\n')


# --------------------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------
# Appearance (light / dark)
# --------------------------------------------------------------------------------------
THEMES = {
    "light": {
        "bg": "#f3f3f3", "bg2": "#e8e8e8", "field": "#ffffff", "fg": "#1f2328", "muted": "#6e7781",
        "border": "#c8ccd1", "button": "#fbfbfb", "button_hover": "#e9eef6", "button_press": "#dbe4f1",
        "select_bg": "#d3efd9", "select_fg": "#1f2328", "accent": "#1a7f37",
        "primary": "#1f883d", "primary_hover": "#1a7f37", "primary_press": "#116329", "primary_fg": "#ffffff",
        "status": {"Online": "#1a7f37", "Starting": "#9a6700", "Stopped": "#6e7781", "Not installed": "#a40e26",
                   "Queued to start": "#0969da"},
        "busy": "#0969da", "good": "#1a7f37", "warn": "#9a6700", "bad": "#a40e26", "off": "#8c959f",
        "chart_bg": "#ffffff", "chart_border": "#d0d7de", "chart_ink": "#1f2328", "chart_muted": "#6e7781",
        "chart_grid": "#eaeef2", "chart_line": "#2f6fd6", "chart_warn": "#9a6700", "chart_cross": "#8c959f",
    },
    "dark": {
        "bg": "#1f2124", "bg2": "#181a1c", "field": "#2a2d31", "fg": "#e6e8eb", "muted": "#9aa1a9",
        "border": "#3d4249", "button": "#30343a", "button_hover": "#3a3f46", "button_press": "#454b53",
        "select_bg": "#1f4a2c", "select_fg": "#ffffff", "accent": "#3fb950",
        "primary": "#238636", "primary_hover": "#2ea043", "primary_press": "#1a7f37", "primary_fg": "#ffffff",
        "status": {"Online": "#3fb950", "Starting": "#d29922", "Stopped": "#8b949e", "Not installed": "#f85149",
                   "Queued to start": "#58a6ff"},
        "busy": "#58a6ff", "good": "#3fb950", "warn": "#d29922", "bad": "#f85149", "off": "#6e7681",
        "chart_bg": "#24272b", "chart_border": "#3d4249", "chart_ink": "#e6e8eb", "chart_muted": "#9aa1a9",
        "chart_grid": "#33373c", "chart_line": "#5b9bff", "chart_warn": "#d29922", "chart_cross": "#6e7681",
    },
}
THEME_CHOICES = [("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")]


def cloud_folders():
    """Detected cloud-synced folders: [(label, path)]."""
    out = []
    for env, label in (("OneDrive", "OneDrive"), ("OneDriveConsumer", "OneDrive"), ("OneDriveCommercial", "OneDrive (work)")):
        p = os.environ.get(env)
        if p and os.path.isdir(p) and p not in [x[1] for x in out]:
            out.append((label, p))
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")):
        info = read_json_file(os.path.join(base, "Dropbox", "info.json")) if base else None
        if info:
            for v in info.values():
                if isinstance(v, dict) and os.path.isdir(v.get("path", "")):
                    out.append(("Dropbox", v["path"]))
                    break
            break
    gd = os.path.join(os.path.expanduser("~"), "Google Drive")
    if os.path.isdir(gd):
        out.append(("Google Drive", gd))
    return out[:3]


def windows_prefers_dark() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def set_dark_titlebar(win, dark: bool):
    """Windows 10 (1809+) / 11: dark window title bar to match the theme."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())  # type: ignore[attr-defined]
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / pre-20H1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),  # type: ignore[attr-defined]
                                                          ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def without_indicator(layout):
    """A copy of a ttk layout with the tree expand arrow taken out."""
    out = []
    for name, opts in layout:
        if "indicator" not in name:
            kids = opts.get("children")
            out.append((name, {**opts, "children": without_indicator(kids)} if kids else opts))
    return out


def mod_mode_images(width, centres, size=18):
    """Pictures for the installed mods list: (Active ticked, Passive ticked).

    Each is `width` pixels wide with two circles, centred at the x positions in `centres`: a green circle
    with a white tick for the chosen mode, an empty one for the other. Built as PNGs here because
    tkinter can't draw smooth shapes on an image, and Tamer has no image library to lean on.
    """
    def segment_dist(x, y, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0, min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)

    def colour_at(x, y, on):
        r = size / 2
        d = math.hypot(x - r, y - r)
        if d > r:
            return None
        if not on:
            return (140, 146, 156) if d >= r - 1.6 else None
        tick = [(r + r * a, r + r * b) for a, b in ((-0.46, 0.04), (-0.12, 0.38), (0.48, -0.32))]
        if min(segment_dist(x, y, tick[0], tick[1]), segment_dist(x, y, tick[1], tick[2])) <= r * 0.13:
            return (255, 255, 255)
        return (46, 160, 67)

    def pixel(px, py, on):
        samples = [colour_at(px + (i + 0.5) / 4, py + (j + 0.5) / 4, on) for i in range(4) for j in range(4)]
        hit = [c for c in samples if c]
        if not hit:
            return bytes(4)
        return bytes(sum(c[n] for c in hit) // len(hit) for n in range(3)) + bytes([255 * len(hit) // 16])

    lefts = [max(0, min(width - size, round(c - size / 2))) for c in centres]

    def rows(first_on):
        for py in range(size):
            row = bytearray(4 * width)
            for left, on in zip(lefts, (first_on, not first_on)):
                row[4 * left:4 * (left + size)] = b"".join(pixel(px, py, on) for px in range(size))
            yield bytes(row)

    return tuple(png_image(width, size, rows(on)) for on in (True, False))


def png_image(width, height, rows):
    """A tk image from RGBA pixel rows (bytes, 4 per pixel)."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\0" + r for r in rows)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return tk.PhotoImage(data=base64.b64encode(data), format="png")


def dot_image(colour, size=10, gap=6):
    """A smooth round dot in `colour` ("#rrggbb"), with `gap` empty pixels after it before the text."""
    rgb = bytes(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    r = size / 2

    def rows():
        for py in range(size):
            row = bytearray(4 * (size + gap))
            for px in range(size):
                inside = sum(math.hypot(px + (i + 0.5) / 4 - r, py + (j + 0.5) / 4 - r) <= r
                             for i in range(4) for j in range(4))
                if inside:
                    row[4 * px:4 * px + 4] = rgb + bytes([255 * inside // 16])
            yield bytes(row)
    return png_image(size + gap, size, rows())


def apply_ttk_theme(root, mode: str) -> dict:
    """Style ttk + classic tk widgets for 'light' or 'dark'. Returns the palette."""
    c = THEMES[mode]
    st = ttk.Style(root)
    st.theme_use("clam")  # both modes: Windows' own "vista" look ignores custom colours
    st.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                 bordercolor=c["border"], darkcolor=c["bg"], lightcolor=c["bg"], troughcolor=c["bg2"],
                 focuscolor=c["accent"], selectbackground=c["select_bg"], selectforeground=c["select_fg"],
                 insertcolor=c["fg"], arrowcolor=c["fg"])
    st.map(".", foreground=[("disabled", c["muted"])], background=[("disabled", c["bg"])])
    st.configure("TButton", background=c["button"], bordercolor=c["border"], lightcolor=c["button"],
                 darkcolor=c["button"], padding=(8, 3))
    st.map("TButton", background=[("disabled", c["bg"]), ("pressed", c["button_press"]), ("active", c["button_hover"])],
           lightcolor=[("pressed", c["button_press"]), ("active", c["button_hover"])],
           darkcolor=[("pressed", c["button_press"]), ("active", c["button_hover"])],
           foreground=[("disabled", c["muted"])], bordercolor=[("focus", c["accent"])])
    st.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"], insertcolor=c["fg"],
                 lightcolor=c["border"], darkcolor=c["border"])
    st.map("TEntry", fieldbackground=[("disabled", c["bg"]), ("readonly", c["bg2"])],
           bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])])
    st.configure("TCombobox", fieldbackground=c["field"], background=c["button"], foreground=c["fg"],
                 arrowcolor=c["fg"], lightcolor=c["border"], darkcolor=c["border"])
    st.map("TCombobox", fieldbackground=[("readonly", c["field"]), ("disabled", c["bg"])],
           foreground=[("readonly", c["fg"]), ("disabled", c["muted"])],
           selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["fg"])],
           background=[("active", c["button_hover"])], bordercolor=[("focus", c["accent"])])
    st.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["fg"],
                 bordercolor=c["border"], lightcolor=c["field"], darkcolor=c["field"])
    st.map("Treeview", background=[("selected", c["select_bg"])], foreground=[("selected", c["select_fg"])])
    st.configure("Treeview.Heading", background=c["button"], foreground=c["fg"], bordercolor=c["border"],
                 lightcolor=c["button"], darkcolor=c["button"], relief="flat")
    st.map("Treeview.Heading", background=[("active", c["button_hover"])])
    st.configure("TNotebook", background=c["bg"], bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"])
    st.configure("TNotebook.Tab", background=c["bg2"], foreground=c["muted"], padding=(10, 4),
                 bordercolor=c["border"], lightcolor=c["bg2"], darkcolor=c["bg2"])
    st.map("TNotebook.Tab", background=[("selected", c["bg"]), ("active", c["button_hover"])],
           foreground=[("selected", c["fg"]), ("active", c["fg"])],
           lightcolor=[("selected", c["bg"])], darkcolor=[("selected", c["bg"])])
    st.configure("TLabelframe", background=c["bg"], bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"])
    st.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=c["bg"], foreground=c["fg"], indicatorbackground=c["field"],
                     indicatorforeground=c["fg"], upperbordercolor=c["border"], lowerbordercolor=c["border"])
        st.map(w, background=[("active", c["bg"])],
               indicatorbackground=[("disabled", c["bg"]), ("pressed", c["button_press"]), ("selected", c["field"])],
               foreground=[("disabled", c["muted"])])
    for orient in ("Vertical", "Horizontal"):
        st.configure(f"{orient}.TScrollbar", background=c["button"], troughcolor=c["bg2"], bordercolor=c["bg2"],
                     arrowcolor=c["fg"], lightcolor=c["button"], darkcolor=c["button"])
        st.map(f"{orient}.TScrollbar", background=[("active", c["button_hover"])])
    st.configure("TPanedwindow", background=c["bg"])
    st.configure("Sash", background=c["bg"], lightcolor=c["bg"], bordercolor=c["bg"])
    # main actions (Start, Install / Update, Save...): green fill, grey again when they can't be used
    st.configure("Accent.TButton", background=c["primary"], foreground=c["primary_fg"], bordercolor=c["primary"],
                 lightcolor=c["primary"], darkcolor=c["primary"])
    st.map("Accent.TButton",
           background=[("disabled", c["button"]), ("pressed", c["primary_press"]), ("active", c["primary_hover"])],
           lightcolor=[("disabled", c["button"]), ("pressed", c["primary_press"]), ("active", c["primary_hover"])],
           darkcolor=[("disabled", c["button"]), ("pressed", c["primary_press"]), ("active", c["primary_hover"])],
           bordercolor=[("disabled", c["border"]), ("focus", c["fg"])],
           foreground=[("disabled", c["muted"])])
    st.configure("Horizontal.TProgressbar", background=c["primary"], troughcolor=c["bg2"], bordercolor=c["border"],
                 lightcolor=c["primary"], darkcolor=c["primary"])
    st.configure("TLabelframe.Label", foreground=c["accent"], font=("Segoe UI", 9, "bold"))
    st.configure("Title.TLabel", foreground=c["accent"], font=("Segoe UI", 11, "bold"))
    st.configure("Header.TLabel", foreground=c["accent"], font=("Segoe UI", 16, "bold"))
    st.configure("Status.TLabel", font=("Segoe UI", 11, "bold"))
    st.configure("Hint.TLabel", foreground=c["muted"])
    st.configure("Warn.TLabel", foreground=c["bad"])
    st.configure("Treeview", rowheight=26)
    # Installed mods list: no gap for an expand arrow, so the circles line up with their headings
    st.layout("Mods.Treeview", st.layout("Treeview"))
    st.layout("Mods.Treeview.Item", without_indicator(st.layout("Treeview.Item")))
    st.layout("Servers.Treeview", st.layout("Treeview"))  # same for the status dots in the server list
    st.layout("Servers.Treeview.Item", without_indicator(st.layout("Treeview.Item")))
    # classic tk widgets (Text, Canvas, dialogs from simpledialog, menus) pick these up when created
    opts = {"*Text.background": c["field"], "*Text.foreground": c["fg"], "*Text.insertBackground": c["fg"],
            "*Text.selectBackground": c["select_bg"], "*Text.selectForeground": c["select_fg"],
            "*Text.highlightBackground": c["border"], "*Text.highlightColor": c["accent"],
            "*Canvas.background": c["bg"], "*Toplevel.background": c["bg"],
            "*Frame.background": c["bg"], "*Label.background": c["bg"], "*Label.foreground": c["fg"],
            "*Entry.background": c["field"], "*Entry.foreground": c["fg"], "*Entry.insertBackground": c["fg"],
            "*Button.background": c["button"], "*Button.foreground": c["fg"],
            "*Button.activeBackground": c["button_hover"], "*Button.activeForeground": c["fg"],
            "*Menu.background": c["field"], "*Menu.foreground": c["fg"],
            "*Menu.activeBackground": c["select_bg"], "*Menu.activeForeground": c["select_fg"],
            "*TCombobox*Listbox.background": c["field"], "*TCombobox*Listbox.foreground": c["fg"],
            "*TCombobox*Listbox.selectBackground": c["select_bg"],
            "*TCombobox*Listbox.selectForeground": c["select_fg"]}
    for k, v in opts.items():
        root.option_add(k, v)
    root.configure(background=c["bg"])
    return c


def recolor_tk_widgets(widget, c):
    """Apply the palette to already-created classic tk widgets (option_add only affects new ones)."""
    stack = [widget]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        try:
            if isinstance(w, tk.Text):
                w.configure(background=c["field"], foreground=c["fg"], insertbackground=c["fg"],
                            selectbackground=c["select_bg"], selectforeground=c["select_fg"],
                            highlightbackground=c["border"], highlightcolor=c["accent"])
            elif isinstance(w, tk.Canvas):
                chart = getattr(w, "is_chart", False)
                w.configure(background=c["chart_bg"] if chart else c["bg"],
                            highlightbackground=c["chart_border"] if chart else c["bg"])
            elif isinstance(w, (tk.Toplevel, tk.Tk)):
                w.configure(background=c["bg"])
            elif isinstance(w, tk.Menu):
                w.configure(background=c["field"], foreground=c["fg"], activebackground=c["select_bg"],
                            activeforeground=c["select_fg"])
            elif isinstance(w, tk.Menubutton):  # the File / Help bar
                w.configure(background=c["bg"], foreground=c["fg"], activebackground=c["button_hover"],
                            activeforeground=c["fg"])
            elif getattr(w, "is_menubar", False):
                w.configure(background=c["bg"])
            elif getattr(w, "is_link", False):  # the Ko-fi link on the menu bar
                w.configure(background=c["bg"], foreground=c["accent"])
            elif isinstance(w, ttk.Combobox):
                pd = w.tk.call("ttk::combobox::PopdownWindow", w)
                w.tk.call(f"{pd}.f.l", "configure", "-background", c["field"], "-foreground", c["fg"],
                          "-selectbackground", c["select_bg"], "-selectforeground", c["select_fg"])
        except tk.TclError:
            pass


class FlowFrame(ttk.Frame):
    """Lays buttons out left to right and wraps them onto extra rows when the window is narrow."""

    def __init__(self, parent, gap=4, **kw):
        super().__init__(parent, **kw)
        self.items = []
        self.gap = gap
        self._width = 0
        self.bind("<Configure>", self._on_configure)

    def add(self, widget):
        self.items.append(widget)
        self.relayout()
        return widget

    def _on_configure(self, e):
        if e.width != self._width:
            self._width = e.width
            self.relayout()

    def relayout(self):
        width = self.winfo_width() if self.winfo_width() > 1 else 10_000
        x = y = row_h = 0
        for w in self.items:
            ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            if x and x + ww > width:
                x, y = 0, y + row_h + self.gap
                row_h = 0
            w.place(x=x, y=y)
            x += ww + self.gap
            row_h = max(row_h, wh)
        height = y + row_h
        if int(self.cget("height") or 0) != height:
            self.configure(height=height)


def initial_sash(pw, fraction, lo=0, hi=10_000):
    """Put a PanedWindow's first divider at a fraction of its size the first time it is shown."""
    vertical = str(pw.cget("orient")) == "vertical"

    def go(_e=None):
        size = pw.winfo_height() if vertical else pw.winfo_width()
        if size > 50 and pw.winfo_ismapped():  # wait until the window has its real size
            top = hi(size) if callable(hi) else hi  # hi can depend on the size, e.g. to leave room on the other side
            pw.sashpos(0, int(max(lo, min(top, size * fraction))))
            pw.unbind("<Configure>", bind_id)

    bind_id = pw.bind("<Configure>", go, add="+")


class ScrollFrame(ttk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        bg = ttk.Style().lookup("TFrame", "background") or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=bg)
        vsb = ttk.Scrollbar(self, orient="vertical", command=lambda *a: self.fits() or self.canvas.yview(*a))
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: (self.canvas.configure(scrollregion=self.canvas.bbox("all")),
                                                  self._top_if_fits()))
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: (self.canvas.itemconfigure(win, width=e.width),
                                                   self._top_if_fits()))
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        if not ScrollFrame._wheel_installed:
            self.bind_all("<MouseWheel>", ScrollFrame._on_wheel, add="+")
            ScrollFrame._wheel_installed = True

    _wheel_installed = False

    def fits(self):
        """True when the whole page is showing, so there's nothing to scroll."""
        return self.inner.winfo_reqheight() <= self.canvas.winfo_height()

    def _top_if_fits(self):
        # Tk lets a page shorter than the canvas slide down inside it, leaving a gap at the top
        if self.fits():
            self.canvas.yview_moveto(0)

    @staticmethod
    def _on_wheel(e):
        try:
            w = e.widget.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return
        while w is not None:
            if isinstance(w, (tk.Text, ttk.Treeview, ttk.Combobox)):
                return
            if isinstance(w, ScrollFrame):
                if w.fits():
                    return
                step = int(-e.delta / 120) or (-1 if e.delta > 0 else 1)
                w.canvas.yview_scroll(step, "units")
                return
            w = w.master


# (section, key, label, kind, hint)
SERVER_FIELDS = [
    ("General", "name", "Profile name", "text", "Name shown in this manager"),
    ("General", "session_name", "Server name (in-game list)", "text", ""),
    ("General", "map", "Map", "map", "Pick a map or type a mod map name"),
    ("General", "max_players", "Max players", "int", ""),
    ("General", "install_dir", "Install folder", "dir", "Use a separate folder per server"),
    ("Network & security", "port", "Game port (UDP)", "int", "Forward this UDP port on your router"),
    ("Network & security", "rcon_port", "RCON port (TCP)", "int", "Don't expose publicly"),
    ("Network & security", "admin_password", "Admin password", "password", "Also used for RCON"),
    ("Network & security", "server_password", "Join password", "password", "Blank = public"),
    ("Mods & cluster", "mods", "CurseForge mod IDs", "text", "Comma separated, e.g. 928988,931874"),
    ("Mods & cluster", "cluster", "Join the cluster", "bool", "Uses the cluster ID/folder in Settings"),
    ("Mods & cluster", "battleye", "Enable BattlEye", "bool", ""),
    ("Advanced", "active_event", "Active event", "event",
     "Sets -ActiveEvent. Most ASA events come as official mods - use 'Find event mod' if nothing changes in game"),
    ("Advanced", "extra_options", "Extra ?options", "text", "e.g. AllowCrateSpawnsOnTopOfStructures=True?PreventSpawnAnimations=True"),
    ("Advanced", "extra_args", "Extra -arguments", "text", "e.g. -ForceAllowCaveFlyers -NoTransferFromFiltering"),
    ("Behaviour", "autostart", "Start when the manager opens", "bool", ""),
    ("Behaviour", "update_on_start", "Update before every start", "bool", ""),
    ("Behaviour", "auto_restart_on_crash", "Auto-restart if it crashes", "bool", ""),
    ("Behaviour", "hide_log_window", "Hide ARK's log window when using AsaApi", "bool",
     "Only the AsaApi window shows. Without AsaApi, ARK's window always stays"),
]
EVENT_CHOICES = ["", "WinterWonderland", "FearEvolved", "TurkeyTrial", "Summer", "Easter", "vday", "Birthday",
                 "Anniversary"]
EVENT_MOD_SEARCH = {"WinterWonderland": "Winter Wonderland", "FearEvolved": "Fear Ascended",
                    "TurkeyTrial": "Turkey Trial", "Summer": "Summer Bash", "Easter": "Eggcellent",
                    "vday": "Love Ascended", "Birthday": "Anniversary", "Anniversary": "Anniversary"}
SCHEDULE_FIELDS = [
    ("Scheduled restarts", "restart_times", "Daily restart times", "text", "24h, comma separated: 04:00, 16:00"),
    ("Scheduled restarts", "restart_warn_minutes", "Warn players at (minutes)", "text", "e.g. 15, 10, 5, 1"),
    ("Scheduled restarts", "update_on_scheduled_restart", "Update game during scheduled restarts", "bool", ""),
    ("Scheduled restarts", "auto_update_restart", "Restart automatically when a game update is released", "bool",
     "Warns players first"),
    ("Automatic restarts", "auto_mod_update_restart", "Restart automatically when an installed mod updates", "bool",
     "Warns players first; check interval is in File > Settings"),
    ("Automatic restarts", "mod_restart_wait_empty", "Wait until the server is empty before a mod update restart", "bool",
     "Restarts as soon as nobody is online"),
    ("Automatic restarts", "mod_restart_wait_minutes", "Longest wait for an empty server (minutes)", "int",
     "After this it restarts anyway, with player warnings. 0 = no limit"),
    ("Automatic restarts", "ram_restart_gb", "Restart if memory use goes above (GB)", "text",
     "0 = off. Watch the Performance tab to pick a value"),
    ("Backups", "backup_interval_min", "Auto backup every (minutes)", "int", "0 = off; only while online"),
    ("Backups", "backup_keep", "Backups to keep", "int", "Oldest are deleted; 0 = keep all"),
    ("Notifications", "discord_notify", "Send Discord notifications for this server", "bool",
     "Webhook and event types are in File > Settings"),
]
INT_KEYS = {"port", "rcon_port", "max_players", "backup_interval_min", "backup_keep"}
FLOAT_KEYS = {"ram_restart_gb"}



class App:
    def __init__(self, root: tk.Tk, took_over=False):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.cfg = AppConfig()
        self.mgr = Manager(self.cfg, lambda kind, sid=None, payload=None: self.q.put((kind, sid, payload)))
        self.sel = None
        self.form_vars: dict[str, tk.Variable] = {}
        self.pw_entries = []
        self.common_vars = {}
        self.ini_texts = {}
        self._dirty_state = False
        self._ini_tab_prev = 0
        self.cf = self.mgr.cf
        self.mod_results = {}
        self._mod_search_token = None
        self._mod_fetch_tried = set()
        self._mod_fetch_failed = set()  # mod IDs whose name couldn't be fetched (shown as "name not found")
        self._tray_hint_shown = False
        self.mgr.autostart_enabled = not took_over  # servers were already being managed by the service
        for srv in self.cfg.servers:
            self.mgr.load_log_tail(srv)
        self.tray = TrayIcon(f"{APP_NAME}", lambda: self.q.put(("call", None, self._show_window)),
                             lambda: self.q.put(("call", None, self._exit))) if IS_WINDOWS else None

        root.title(f"{APP_NAME} - {APP_TAGLINE}   (v{APP_VERSION})")
        self._set_window_icon()
        self._restore_window_geometry()
        root.minsize(860, 520)
        self._style()
        self._menu()
        self._layout()
        self._refresh_server_list()
        if self.cfg.servers:
            self.tree.selection_set(self.cfg.servers[0]["id"])
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<Unmap>", self._on_unmap)
        self.apply_theme()
        root.after(15000, self._watch_system_theme)
        root.after(150, self._pump)
        root.after(20000, self._tamer_update_tick)
        if self.cfg.first_run or not self.cfg.servers:  # nothing to show yet: help set one up (or import one)
            root.after(600, self._welcome)
        self.mgr.start_monitor()

    # ---- look & feel -------------------------------------------------------------
    def _restore_window_geometry(self):
        """Open at the last size/position if it fits this screen, else at a size that fits."""
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        win = self.cfg.data.get("window") or {}
        m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", win.get("geometry", ""))
        if m:
            w, h, x, y = map(int, m.groups())
            if w <= sw and h <= sh and -50 <= x <= sw - 200 and -10 <= y <= sh - 150:
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            else:
                m = None
        if not m:
            w, h = min(1280, sw - 60), min(820, sh - 90)  # leave room for the taskbar
            self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")
        if win.get("zoomed") and IS_WINDOWS:
            self.root.after(50, lambda: self.root.state("zoomed"))

    def _save_window_geometry(self):
        try:
            win = dict(self.cfg.data.get("window") or {})
            zoomed = self.root.state() == "zoomed"
            win["zoomed"] = zoomed
            if self.root.state() == "normal":
                win["geometry"] = self.root.geometry()
            self.cfg.data["window"] = win
            self.cfg.save()
        except tk.TclError:
            pass

    def _set_window_icon(self):
        try:
            if IS_WINDOWS and os.path.isfile(ICON_ICO):
                # The .ico has every size Windows asks for. iconphoto here would replace it with Tk's own icon,
                # and default= alone only reaches dialogs, not this window.
                self.root.iconbitmap(ICON_ICO)
                self.root.iconbitmap(default=ICON_ICO)
            elif os.path.isfile(ICON_PNG):
                self._icon_img = tk.PhotoImage(file=ICON_PNG)
                self.root.iconphoto(True, self._icon_img)  # True = also used by every dialog
        except tk.TclError:
            pass

    def _effective_theme(self):
        pref = self.cfg.data.get("theme", "system")
        if pref == "system":
            return "dark" if windows_prefers_dark() else "light"
        return pref if pref in THEMES else "light"

    def _style(self):
        self.theme_mode = self._effective_theme()
        self.colors = apply_ttk_theme(self.root, self.theme_mode)
        self.status_dots = {state: dot_image(colour, size=12)
                            for state, colour in {**self.colors["status"], "busy": self.colors["busy"]}.items()}

    def apply_theme(self):
        """Switch light/dark at runtime."""
        self._style()
        c = self.colors
        recolor_tk_widgets(self.root, c)
        set_dark_titlebar(self.root, self.theme_mode == "dark")
        for state, color in c["status"].items():
            self.tree.tag_configure(state, foreground=color)
        self.tree.tag_configure("busy", foreground=c["busy"])
        self._refresh_server_list()  # new dots
        self.mtree.tag_configure("installed", foreground=c["good"])
        self.task_tree.tag_configure("off", foreground=c["off"])
        self.plugin_tree.tag_configure("off", foreground=c["off"])
        self.itree.tag_configure("passive", foreground=c["muted"])
        self._mod_mode_layout()
        self._refresh_installed_mods()
        self.plugin_tree.tag_configure("bad", foreground=c["bad"])
        self._refresh_header()
        self._refresh_perf()

    def themed_window(self, win):
        """Call on every new Toplevel so dialogs match the theme."""
        win.configure(background=self.colors["bg"])
        recolor_tk_widgets(win, self.colors)
        set_dark_titlebar(win, self.theme_mode == "dark")

    # ---- first-run welcome ---------------------------------------------------------
    def _welcome(self):
        """Step-by-step setup of a first server. The very first time it fills in the starting server; run again
        from the Help menu it adds a new one, so it never changes a server someone already set up."""
        if getattr(self, "welcome_win", None) is not None and self.welcome_win.winfo_exists():
            self.welcome_win.lift()
            return
        fresh = self.cfg.first_run and len(self.cfg.servers) == 1 and not self.mgr.is_installed(self.cfg.servers[0])
        self.cfg.first_run = False
        target = self.cfg.servers[0] if fresh else default_server(len(self.cfg.servers) + 1, self.cfg.servers)
        d = self.welcome_win = tk.Toplevel(self.root)
        d.title("Welcome to Tamer")
        d.transient(self.root)
        d.resizable(False, False)
        body = ttk.Frame(d, padding=(18, 14))
        body.pack(fill="both", expand=True)
        folder = tk.StringVar(value=self.cfg.data.get("servers_dir") or roomiest_drive()[0])
        name = tk.StringVar(value="My ARK Server" if fresh else target["session_name"])
        map_labels = [m[0] for m in MAPS]
        map_var = tk.StringVar(value=MAP_LABELS.get(target["map"], map_labels[0]))
        players = tk.StringVar(value=str(target["max_players"]))
        join_pw = tk.StringVar(value="")
        port = tk.StringVar(value=str(target["port"]))
        rcon = tk.StringVar(value=str(target["rcon_port"]))
        install = tk.BooleanVar(value=True)
        pages, step = [], [0]

        def page(title, intro):
            f = ttk.Frame(body)
            f.columnconfigure(1, weight=1)
            ttk.Label(f, text=title, style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
            ttk.Label(f, text=intro, style="Hint.TLabel", wraplength=520, justify="left").grid(
                row=1, column=0, columnspan=3, sticky="w", pady=(2, 12))
            pages.append(f)
            return f

        def field(f, row, label, var, width=40, **kw):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            e = ttk.Entry(f, textvariable=var, width=width, **kw)
            e.grid(row=row, column=1, sticky="w", pady=4)
            return e

        f = page("Welcome to Tamer", "Tamer installs, runs and looks after ARK: Survival Ascended dedicated servers: "
                                     "updates, backups, mods, crash restarts and more.\n\nThis sets up your first server "
                                     "in four short steps. You can change everything later, or click Skip.")
        ttk.Button(f, text="Already have a server? Import it instead...",
                   command=lambda: (d.destroy(), self._import_dialog(replace=target if fresh else None))).grid(
            row=2, column=0, columnspan=3, sticky="w")
        f = page("Where to keep your servers", "Each ARK server takes about 13 GB. Tamer picked the drive with the "
                                               "most free space; new servers go in this folder too.")
        field(f, 2, "Servers folder", folder, width=46)
        ttk.Button(f, text="Browse...", command=lambda: self._browse_dir(folder)).grid(row=2, column=2, padx=6)
        space = ttk.Label(f, text="", style="Hint.TLabel")
        space.grid(row=3, column=1, columnspan=2, sticky="w")

        def show_space(*_):
            p = os.path.abspath(folder.get().strip() or ".")
            while p and not os.path.exists(p) and os.path.dirname(p) != p:
                p = os.path.dirname(p)
            try:
                free = shutil.disk_usage(p).free / 1024 ** 3
            except OSError:
                space.configure(text="", style="Hint.TLabel")
                return
            low = free < 20
            space.configure(text=f"{free:.0f} GB free there" + (" - that's tight for an ARK server (about 13 GB "
                                                                 "plus saves and updates)" if low else ""),
                            style="Warn.TLabel" if low else "Hint.TLabel")
        folder.trace_add("write", show_space)
        show_space()
        f = page("Your server", "The name is what players see in the server list.")
        field(f, 2, "Server name", name)
        ttk.Label(f, text="Map").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=map_var, values=map_labels, state="readonly", width=24).grid(
            row=3, column=1, sticky="w", pady=4)
        field(f, 4, "Max players", players, width=8)
        field(f, 5, "Join password", join_pw, width=24)
        ttk.Label(f, text="Leave the join password blank for a public server. An admin password is made for you "
                          "(it's on the Server tab).", style="Hint.TLabel", wraplength=520, justify="left").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        f = page("Ports", "These defaults are fine for one server; Tamer picks free ones for the next.")
        field(f, 2, "Game port (UDP)", port, width=8)
        field(f, 3, "RCON port (TCP)", rcon, width=8)
        ttk.Label(f, text="For friends outside your home to join, forward the game port (UDP) on your router to "
                          "this PC. Don't forward the RCON port. 'Check connectivity' on the main window tests it "
                          "for you later.", style="Hint.TLabel", wraplength=520, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        f = page("All set", "")
        summary = ttk.Label(f, text="", justify="left")
        summary.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f, text="Install the server now (downloads about 13 GB - the Log tab shows progress)",
                        variable=install).grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))

        def problem():
            """What's wrong on the current page, or ""."""
            if step[0] == 1:
                p = folder.get().strip()
                if not p or not os.path.isabs(p):
                    return "Pick a full folder path, like D:\\ARK Servers."
            elif step[0] == 2:
                if not name.get().strip():
                    return "Give the server a name."
                if not players.get().strip().isdigit() or not 1 <= int(players.get()) <= 255:
                    return "Max players should be a number from 1 to 255."
            elif step[0] == 3:
                ports = [port.get().strip(), rcon.get().strip()]
                if not all(x.isdigit() and 1 <= int(x) <= 65535 for x in ports):
                    return "Ports are numbers from 1 to 65535."
                if ports[0] == ports[1]:
                    return "The game port and the RCON port must be different."
            return ""

        nav = ttk.Frame(d, padding=(18, 0, 18, 14))
        nav.pack(fill="x")
        b_skip = ttk.Button(nav, text="Skip", command=d.destroy)
        b_skip.pack(side="left")
        b_next = ttk.Button(nav, text="Next", style="Accent.TButton")
        b_next.pack(side="right")
        b_back = ttk.Button(nav, text="Back")
        b_back.pack(side="right", padx=6)

        def show(i):
            step[0] = i
            for p in pages:
                p.pack_forget()
            pages[i].pack(fill="both", expand=True)
            b_back.configure(state="normal" if i else "disabled")
            b_next.configure(text="Finish" if i == len(pages) - 1 else "Next")
            if i == len(pages) - 1:
                summary.configure(text=f"Server: {name.get().strip()}\nMap: {map_var.get()}\n"
                                       f"Folder: {os.path.join(folder.get().strip(), safe_name(name.get().strip()))}\n"
                                       f"Ports: game {port.get().strip()}, RCON {rcon.get().strip()}")

        def nxt():
            err = problem()
            if err:
                messagebox.showerror(APP_NAME, err, parent=d)
                return
            if step[0] < len(pages) - 1:
                show(step[0] + 1)
                return
            root_dir, nm = folder.get().strip(), name.get().strip()
            try:
                os.makedirs(root_dir, exist_ok=True)
            except OSError as e:
                messagebox.showerror(APP_NAME, f"Couldn't create {root_dir}:\n{e}\n\nPick another folder.", parent=d)
                show(1)
                return
            target.update(name=nm, session_name=nm, map=dict((m[0], m[1]) for m in MAPS)[map_var.get()],
                          max_players=int(players.get()), server_password=join_pw.get().strip(),
                          port=int(port.get()), rcon_port=int(rcon.get()),
                          install_dir=os.path.join(root_dir, safe_name(nm)))
            self.cfg.data["servers_dir"] = root_dir
            if target not in self.cfg.servers:
                self.cfg.servers.append(target)
            self.cfg.save()
            d.destroy()
            self.sel = None
            self._refresh_server_list()
            self.tree.selection_set(target["id"])
            self._on_select()
            if install.get():
                self._update()

        b_next.configure(command=nxt)
        b_back.configure(command=lambda: show(step[0] - 1))
        show(0)
        self.themed_window(d)
        d.grab_set()

    # ---- import a server Tamer didn't make -----------------------------------------
    def _import_dialog(self, replace=None):
        """replace: the untouched starter server, when this is opened from the first-run welcome."""
        if getattr(self, "import_win", None) is not None and self.import_win.winfo_exists():
            self.import_win.lift()
            return
        d = self.import_win = tk.Toplevel(self.root)
        d.title("Import existing server")
        d.transient(self.root)
        body = ttk.Frame(d, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Bring a server Tamer didn't set up - made by hand, with a .bat file or with another "
                             "manager - into Tamer. Its files stay where they are, so all its settings and saves come "
                             "with it.", style="Hint.TLabel", wraplength=620, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        src = tk.StringVar(value="running")
        bat_var, dir_var = tk.StringVar(), tk.StringVar()
        ttk.Radiobutton(body, text="A server that's running now (best - Tamer reads exactly how it was started)",
                        variable=src, value="running").grid(row=1, column=0, columnspan=3, sticky="w")
        procs = ttk.Treeview(body, columns=("port", "path"), show="headings", height=4, selectmode="browse")
        procs.heading("port", text="Port")
        procs.heading("path", text="Server")
        procs.column("port", width=70, stretch=False)
        procs.column("path", width=520)
        procs.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(22, 0), pady=2)
        ttk.Button(body, text="Refresh", command=lambda: scan()).grid(row=2, column=2, sticky="n", padx=6, pady=2)
        ttk.Radiobutton(body, text="Its .bat start file", variable=src, value="bat").grid(
            row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(body, textvariable=bat_var, width=60).grid(row=3, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(body, text="Browse...", command=lambda: (bat_var.set(filedialog.askopenfilename(
            parent=d, title="The server's .bat file", filetypes=[("Batch files", "*.bat *.cmd"), ("All files", "*.*")]))
            or bat_var.get(), src.set("bat"))).grid(row=3, column=2, padx=6, pady=(6, 0))
        ttk.Radiobutton(body, text="Just its folder", variable=src, value="folder").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=dir_var, width=60).grid(row=4, column=1, sticky="ew", pady=4)
        ttk.Button(body, text="Browse...", command=lambda: (self._browse_dir(dir_var), src.set("folder"))).grid(
            row=4, column=2, padx=6, pady=4)
        ttk.Button(body, text="Read its settings", command=lambda: read()).grid(row=5, column=0, sticky="w", pady=(8, 4))
        ttk.Label(body, text="Name in Tamer").grid(row=6, column=0, sticky="w")
        name_var = tk.StringVar()
        ttk.Entry(body, textvariable=name_var, width=40).grid(row=6, column=1, sticky="w")
        preview = tk.Text(body, height=18, width=88, wrap="word", state="disabled", font="TkDefaultFont")
        preview.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        body.rowconfigure(7, weight=1)
        bb = ttk.Frame(body)
        bb.grid(row=8, column=0, columnspan=3, sticky="e", pady=(10, 0))
        b_import = ttk.Button(bb, text="Import", style="Accent.TButton", state="disabled", command=lambda: do_import())
        b_import.pack(side="right")
        ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="right", padx=6)
        lines, result = {}, {}

        def scan():
            procs.delete(*procs.get_children())
            procs.insert("", "end", iid="wait", values=("", "Looking for running ARK servers..."))

            def work():
                managed = {os.path.normcase(os.path.normpath(Manager.exe_path(o))) for o in self.cfg.servers}
                found = [(pid, path, cmd) for pid, path, cmd in scan_server_processes()
                         if path and os.path.normcase(os.path.normpath(path)) not in managed]

                def show():
                    if not d.winfo_exists():
                        return
                    procs.delete(*procs.get_children())
                    lines.clear()
                    for pid, path, cmd in found:
                        port = parse_server_cmdline(cmd)[0].get("port", "")
                        lines[str(pid)] = cmd
                        procs.insert("", "end", iid=str(pid), values=(port, server_root_of(path) or path))
                    if not found:
                        procs.insert("", "end", iid="none", values=("", "No running servers that Tamer isn't "
                                                                        "already managing."))
                    elif len(found) == 1:
                        procs.selection_set(str(found[0][0]))
                self.q.put(("call", None, show))
            threading.Thread(target=work, daemon=True).start()

        def read():
            try:
                if src.get() == "running":
                    sel = [i for i in procs.selection() if i in lines]
                    if not sel:
                        raise RuntimeError("Pick the running server in the list first.")
                    s, found, notes = import_server(self.cfg, cmdline=lines[sel[0]])
                elif src.get() == "bat":
                    if not os.path.isfile(bat_var.get().strip()):
                        raise RuntimeError("Pick the server's .bat file first.")
                    s, found, notes = import_server(self.cfg, bat=bat_var.get().strip())
                else:
                    if not os.path.isdir(dir_var.get().strip()):
                        raise RuntimeError("Pick the server's folder first.")
                    s, found, notes = import_server(self.cfg, folder=dir_var.get().strip())
            except RuntimeError as e:
                messagebox.showerror(APP_NAME, str(e), parent=d)
                return
            result.update(s=s, found=found)
            name_var.set(s["name"])
            mods = [m for m in s.get("mods", "").split(",") if m.strip()]
            passive = [m for m in s.get("passive_mods", "").split(",") if m.strip()]
            rows = [("Folder", s["install_dir"]), ("Map", f"{MAP_LABELS.get(s['map'], s['map'])} ({s['map']})"),
                    ("Name in the server list", s["session_name"]),
                    ("Ports", f"game {s['port']}, RCON {s['rcon_port']}"), ("Max players", s["max_players"]),
                    ("Admin password", "found (hidden)" if s.get("admin_password") else "none - one is made for you"),
                    ("Join password", "found (hidden)" if s.get("server_password") else "none (public)"),
                    ("Mods", f"{len(mods)}: {', '.join(mods)}" if mods else "none"),
                    ("Passive mods", ", ".join(passive) or "none"),
                    ("Cluster", f"yes (ID {found['cluster_id']})" if found.get("cluster_id") else "no"),
                    ("AsaApi", "yes" if s.get("asaapi") else "no"), ("BattlEye", "on" if s.get("battleye") else "off"),
                    ("Flags", " ".join(s.get("cmd_flags", [])) or "none"),
                    ("Extra ?options", s.get("extra_options") or "none"),
                    ("Extra -arguments", s.get("extra_args") or "none"),
                    ("Game settings", "GameUserSettings.ini and Game.ini stay in the folder - see the Game settings tab")]
            text = "\n".join(f"{k}: {v}" for k, v in rows)
            if notes:
                text += "\n\n" + "\n".join(f"⚠ {n}" for n in notes)
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert("end", text)
            preview.configure(state="disabled")
            b_import.configure(state="normal")

        def do_import():
            s, found = result["s"], result["found"]
            s["name"] = name_var.get().strip() or s["name"]
            cid = found.get("cluster_id")
            if cid and cid != self.cfg.data["cluster_id"]:
                others = [o["name"] for o in self.cfg.servers if o.get("cluster")]
                ans = messagebox.askyesnocancel(
                    APP_NAME, f"This server uses cluster ID '{cid}', but Tamer's cluster ID is "
                              f"'{self.cfg.data['cluster_id']}'.\n\nYes = use '{cid}' as Tamer's cluster ID" +
                              (f" (your other cluster servers - {', '.join(others)} - switch to it too)" if others else "") +
                              f".\nNo = keep Tamer's, so this server joins Tamer's cluster from its next start.", parent=d)
                if ans is None:
                    return
                if ans:
                    self.cfg.data["cluster_id"] = cid
                    if found.get("cluster_dir"):
                        self.cfg.data["cluster_dir"] = found["cluster_dir"]
            if replace in self.cfg.servers and not self.mgr.is_installed(replace):
                self.cfg.servers.remove(replace)  # the welcome's empty starter server isn't needed any more
            self.cfg.servers.append(s)
            self.cfg.save()
            d.destroy()
            self.sel = None
            self._refresh_server_list()
            self.tree.selection_set(s["id"])
            self._on_select()
            self.mgr.log(s, f"Imported from {s['install_dir']}.")
            threading.Thread(target=self.mgr.adopt_processes, daemon=True).start()  # pick it up if it's running
            messagebox.showinfo(APP_NAME, f"'{s['name']}' is imported. Check its Server and Game settings tabs.\n\n"
                                          "If it's running, Tamer is watching it now. If another manager was looking "
                                          "after it, switch that off, so the two don't both restart it.")

        procs.bind("<<TreeviewSelect>>", lambda e: src.set("running"))
        scan()
        self.themed_window(d)
        d.grab_set()

    # ---- Tamer's own updates ------------------------------------------------------
    def _tamer_update_tick(self):
        """Look for a newer Tamer soon after opening, then once a day (if the setting is on)."""
        if self.cfg.data.get("tamer_update_check", True):
            self._tamer_update_check()
        self.root.after(24 * 3600 * 1000, self._tamer_update_tick)

    def _tamer_update_check(self, manual=False):
        def work():
            try:
                rel = tamer_latest()
            except Exception as e:
                if manual:
                    self.q.put(("info", None, f"Couldn't check for Tamer updates.\n\n{e}"))
                return
            newer = version_tuple(rel["version"]) > version_tuple(APP_VERSION)

            def show():
                self.tamer_update = rel if newer else None
                if newer:
                    self.update_link.configure(text=f"⬆ Update to {rel['version']}")
                    self.update_link.pack(side="right", after=self.kofi_link)  # packed after = further left
                else:
                    self.update_link.pack_forget()
                if manual:
                    if newer:
                        self._tamer_update_dialog()
                    else:
                        messagebox.showinfo(APP_NAME, f"You have the latest Tamer ({APP_VERSION}).")
            self.q.put(("call", None, show))
        threading.Thread(target=work, daemon=True).start()

    def _tamer_update_dialog(self):
        rel = self.tamer_update
        if not rel:
            return
        notes = plain_notes(rel["notes"])
        notes = notes[:1200] + ("..." if len(notes) > 1200 else "")
        msg = f"Tamer {rel['version']} is out. You have {APP_VERSION}.\n\n" + (f"What's new:\n{notes}\n\n" if notes else "")
        if rel["url"] and tamer_installed_copy():
            if messagebox.askyesno(APP_NAME, msg + "Download and install it now? Tamer closes while it updates; "
                                                   "your settings are kept and your servers keep running."):
                self._tamer_update_install(rel)
        else:
            why = ("" if rel["url"] else "This release has no installer attached.\n\n") if tamer_installed_copy() else \
                  ("This copy of Tamer wasn't set up with the installer, so it can't update itself. Download the "
                   "new version from the release page.\n\n")
            if messagebox.askyesno(APP_NAME, msg + why + "Open the release page?"):
                webbrowser.open(rel["page"])

    def _tamer_update_install(self, rel):
        """Download the new installer with a progress window (and Cancel), then run it and close."""
        target = os.path.join(tempfile.gettempdir(), rel["name"])
        state = {"got": 0, "total": 0, "error": None, "done": False}
        cancel = threading.Event()
        d = self.update_win = tk.Toplevel(self.root)
        d.title("Updating Tamer")
        d.transient(self.root)
        d.resizable(False, False)
        body = ttk.Frame(d, padding=16)
        body.pack(fill="both", expand=True)
        title = ttk.Label(body, text=f"Downloading Tamer {rel['version']}...", style="Status.TLabel")
        title.pack(anchor="w")
        bar = ttk.Progressbar(body, length=380, mode="indeterminate")
        bar.pack(fill="x", pady=(10, 4))
        bar.start(12)
        amount = ttk.Label(body, text="Connecting to GitHub...", style="Hint.TLabel")
        amount.pack(anchor="w")
        b_cancel = ttk.Button(body, text="Cancel", command=lambda: (cancel.set(), update_log("Download cancelled.")))
        b_cancel.pack(anchor="e", pady=(10, 0))
        d.protocol("WM_DELETE_WINDOW", cancel.set)
        update_log(f"Updating from {APP_VERSION} to {rel['version']}: downloading {rel['url']}")

        def work():
            try:
                req = urllib.request.Request(rel["url"], headers={"User-Agent": f"Tamer/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=60) as r, open(target + ".part", "wb") as f:
                    state["total"] = int(r.headers.get("Content-Length") or 0)
                    while not cancel.is_set():
                        chunk = r.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        state["got"] += len(chunk)
                if cancel.is_set():
                    os.remove(target + ".part")
                    return
                if state["total"] and state["got"] != state["total"]:
                    raise RuntimeError(f"the download stopped early ({state['got']} of {state['total']} bytes)")
                os.replace(target + ".part", target)
                update_log(f"Downloaded {state['got']} bytes to {target}")
            except Exception as e:
                state["error"] = e
                update_log(f"Download failed: {e!r}")
            finally:
                state["done"] = True

        def tick():
            if not d.winfo_exists():
                return
            mb = 1024 * 1024
            if state["total"]:
                if str(bar.cget("mode")) != "determinate":
                    bar.stop()
                    bar.configure(mode="determinate", maximum=state["total"])
                bar.configure(value=state["got"])
                amount.configure(text=f"{state['got'] / mb:.1f} of {state['total'] / mb:.1f} MB")
            elif state["got"]:
                amount.configure(text=f"{state['got'] / mb:.1f} MB")
            if not state["done"]:
                d.after(150, tick)
                return
            if cancel.is_set():
                d.destroy()
                return
            if state["error"]:
                d.destroy()
                if messagebox.askyesno(APP_NAME, f"Couldn't download the update: {state['error']}.\n\nCheck this PC "
                                                 "can reach github.com, or download the installer yourself. Open the "
                                                 "release page?"):
                    webbrowser.open(rel["page"])
                return
            title.configure(text="Starting the installer...")
            b_cancel.configure(state="disabled")
            d.update()
            try:
                subprocess.Popen([target], close_fds=True, env=clean_child_env())  # it opens the new Tamer at the end
            except OSError as e:
                update_log(f"Couldn't start the installer: {e!r}")
                d.destroy()
                messagebox.showerror(APP_NAME, f"Couldn't start the installer ({e}).\n\nIt's saved here - run it "
                                               f"yourself:\n{target}")
                return
            update_log("Installer started; closing Tamer so it can be replaced.")
            d.destroy()
            self._exit()  # the installer replaces Tamer.exe, so get out of its way

        threading.Thread(target=work, daemon=True).start()
        self.themed_window(d)
        d.after(150, tick)

    def _watch_system_theme(self):
        if self.cfg.data.get("theme", "system") == "system" and self._effective_theme() != self.theme_mode:
            self.apply_theme()
        self.root.after(15000, self._watch_system_theme)

    def _menu(self):
        # Windows draws a normal menu bar itself, always light. This one is drawn by Tk, so it follows the theme.
        # Tk doesn't open it with Alt+letter on Windows, so Alt+F and Alt+H are bound here.
        bar = tk.Frame(self.root)
        bar.is_menubar = True
        bar.pack(side="top", fill="x")
        self.menubar = bar
        mb = {}
        for name in ("File", "Help"):
            btn = tk.Menubutton(bar, text=name, underline=0, relief="flat", borderwidth=0, padx=10, pady=3)
            btn.pack(side="left")
            mb[name] = btn
            for key in (name[0].lower(), name[0]):
                self.root.bind(f"<Alt-KeyPress-{key}>", lambda e, b=btn: (self.root.tk.call("tk::MbPost", b), "break")[1])
        fm = tk.Menu(mb["File"], tearoff=False)
        fm.add_command(label="Settings...", command=self._settings_dialog)
        fm.add_command(label="Import existing server...", command=self._import_dialog)
        fm.add_command(label="Update all servers...", command=self._update_all_dialog)
        fm.add_command(label="Broadcast to all servers...", command=self._broadcast_all)
        fm.add_command(label="Stagger restart times...", command=self._stagger_dialog)
        fm.add_command(label="Check for game update now", command=lambda: threading.Thread(
            target=self.mgr.check_updates, args=(True,), daemon=True).start())
        fm.add_command(label="Check for mod updates now", command=lambda: threading.Thread(
            target=self.mgr.check_mod_updates, kwargs={"manual": True}, daemon=True).start())
        fm.add_separator()
        fm.add_command(label="Open manager folder", command=lambda: open_path(BASE_DIR))
        fm.add_command(label="Open backups folder", command=self._open_backup_root)
        fm.add_command(label="Open cluster folder", command=self._open_cluster_dir)
        fm.add_separator()
        fm.add_command(label="Exit", command=self._exit)
        mb["File"]["menu"] = fm
        hm = tk.Menu(mb["Help"], tearoff=False)
        hm.add_command(label="Server configuration reference (wiki)", command=lambda: webbrowser.open(DOCS_URL))
        hm.add_command(label=f"About {APP_NAME}", command=lambda: messagebox.showinfo(
            APP_NAME, f"{APP_NAME} - {APP_TAGLINE}\nVersion {APP_VERSION}\n\n"
                      "An unofficial server manager for ARK: Survival Ascended.\n"
                      "Not affiliated with or endorsed by Studio Wildcard.\n\n"
                      f"Data folder: {DATA_DIR}"))
        hm.add_command(label="Support Tamer on Ko-fi", command=lambda: webbrowser.open(KOFI_URL))
        hm.add_command(label="Check for Tamer updates now", command=lambda: self._tamer_update_check(manual=True))
        hm.add_command(label="Run the welcome again (set up a server)...", command=self._welcome)
        mb["Help"]["menu"] = hm
        # top-right corner: a small link to the Ko-fi page
        kofi = tk.Label(bar, text="☕ Support Tamer", cursor="hand2", padx=10, font=("Segoe UI", 9, "bold"))
        kofi.is_link = True
        kofi.pack(side="right")
        kofi.bind("<Button-1>", lambda e: webbrowser.open(KOFI_URL))
        kofi.bind("<Enter>", lambda e: kofi.configure(font=("Segoe UI", 9, "bold", "underline")))
        kofi.bind("<Leave>", lambda e: kofi.configure(font=("Segoe UI", 9, "bold")))
        self.kofi_link = kofi
        # shown next to it when a newer Tamer is out (see _tamer_update_check)
        upd = tk.Label(bar, text="", cursor="hand2", padx=10, font=("Segoe UI", 9, "bold"))
        upd.is_link = True
        upd.bind("<Button-1>", lambda e: self._tamer_update_dialog())
        upd.bind("<Enter>", lambda e: upd.configure(font=("Segoe UI", 9, "bold", "underline")))
        upd.bind("<Leave>", lambda e: upd.configure(font=("Segoe UI", 9, "bold")))
        self.update_link = upd
        self.tamer_update = None  # tamer_latest() result when it's newer than this copy
        recolor_tk_widgets(bar, self.colors)

    def _layout(self):
        pw = ttk.PanedWindow(self.root, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6, pady=6)

        # left: server list
        left = ttk.Frame(pw)
        pw.add(left, weight=0)
        # Column widths come from the text, so they still fit when Windows display scaling makes it bigger.
        # The list starts wide enough to show them all, but leaves the tab names on the right room to show in
        # full; when both don't fit, Name and Map give way (Status and Players keep their size). The divider drags.
        font = tkfont.nametofont("TkDefaultFont")
        name_w = font.measure("Server 10") + 12 + 30  # + the status dot
        map_w = font.measure("The Island") + 16
        status_w = max(font.measure(t) for t in ["Status", *self.colors["status"]]) + 16
        players_w = font.measure("Players") + 16
        self.server_cols_w = name_w + map_w + status_w + players_w

        def list_width(size):
            tabs_w = sum(font.measure(self.nb.tab(t, "text")) + 26 for t in self.nb.tabs()) + 40
            return min(self.server_cols_w + 24, size - tabs_w)
        initial_sash(pw, 0.45, lo=230, hi=list_width)
        ttk.Label(left, text="Servers", style="Title.TLabel").pack(anchor="w")
        cols = ("map", "status", "players")
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="browse", height=4,
                                 style="Servers.Treeview")
        self.tree.heading("#0", text="Name")
        self.tree.heading("map", text="Map")
        self.tree.heading("status", text="Status")
        self.tree.heading("players", text="Players")
        self.tree.column("#0", width=name_w, minwidth=70)
        self.tree.column("map", width=map_w, minwidth=50)
        self.tree.column("status", width=status_w, minwidth=status_w, stretch=False)
        self.tree.column("players", width=players_w, minwidth=players_w, anchor="center", stretch=False)
        for state, color in self.colors["status"].items():
            self.tree.tag_configure(state, foreground=color)
        self.tree.tag_configure("busy", foreground=self.colors["busy"])
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        b2 = ttk.Frame(left)
        b = ttk.Frame(left)
        for i, (text, cmd) in enumerate([("Add", self._add_server), ("Clone", self._clone_server),
                                         ("Remove", self._remove_server)]):
            b.columnconfigure(i, weight=1, uniform="srvbtn")  # equal widths that shrink together
            ttk.Button(b, text=text, command=cmd, width=1).grid(row=0, column=i, sticky="ew")
        for i, (text, cmd) in enumerate([("Start all", self._start_all), ("Stop all", self._stop_all),
                                         ("Update all", self._update_all_dialog)]):
            b2.columnconfigure(i, weight=1, uniform="allbtn")
            ttk.Button(b2, text=text, command=cmd, width=1,
                       style="Accent.TButton" if i == 0 else "TButton").grid(row=0, column=i, sticky="ew")
        ttk.Button(b2, text="Broadcast to all servers...", command=self._broadcast_all).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Button(b2, text="Copy to other servers...", command=self._copy_dialog).grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.cluster_lbl = ttk.Label(left, style="Hint.TLabel", wraplength=230, justify="left")
        self.cluster_lbl.pack(side="bottom", anchor="w", pady=(8, 0))
        left.bind("<Configure>", lambda e: self.cluster_lbl.configure(wraplength=max(120, e.width - 8)), add="+")
        b2.pack(side="bottom", fill="x", pady=(4, 0))
        b.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True, pady=(4, 4))

        # right: details
        right = ttk.Frame(pw)
        pw.add(right, weight=1)
        head = ttk.Frame(right)
        head.pack(fill="x", padx=8)
        self.h_name = ttk.Label(head, text="", style="Header.TLabel")
        self.h_name.pack(side="left")
        self.h_status = ttk.Label(head, text="", style="Status.TLabel")
        self.h_status.pack(side="left", padx=14)
        self.h_info = ttk.Label(right, text="", style="Hint.TLabel")
        self.h_info.pack(fill="x", padx=8)

        tb = FlowFrame(right)
        tb.pack(fill="x", padx=8, pady=(6, 6))
        self.toolbar = tb
        self.btns = {}
        for key, text, cmd in [
            ("start", "Start", self._start),
            ("stop", "Stop", self._stop),
            ("restart", "Restart", self._restart),
            ("restart_warn", "Restart w/ warnings", lambda: self._restart(warn=True)),
            ("cancel", "Cancel countdown", self._cancel),
            ("update", "Install / Update", self._update),
            ("validate", "Validate files", lambda: self._update(validate=True)),
            ("backup", "Backup now", self._backup_now),
            ("kill", "Force kill", self._kill),
        ]:
            style = "Accent.TButton" if key in ("start", "update") else "TButton"
            self.btns[key] = tb.add(ttk.Button(tb, text=text, command=cmd, style=style))
        for text, cmd in [("Troubleshoot", self._troubleshoot), ("Check connectivity", self._connectivity),
                          ("Open firewall port", self._firewall),
                          ("Server folder", lambda: self._open_rel("")),
                          ("Config folder", lambda: self._open_rel(CONFIG_REL)),
                          ("ShooterGame.log", lambda: self._open_rel(GAMELOG_REL))]:
            tb.add(ttk.Button(tb, text=text, command=cmd))

        self.nb = ttk.Notebook(right)
        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=8, pady=(6, 10))  # toolbar | tabs
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._tab_server()
        self._tab_cmdline()
        self._tab_config()
        self._tab_mods()
        self._tab_plugins()
        self._tab_rcon()
        self._tab_schedule()
        self._tab_tasks()
        self._tab_perf()
        self._tab_log()

    # ---- tabs ---------------------------------------------------------------------
    def _build_fields(self, parent, fields):
        groups = {}
        for section, key, label, kind, hint in fields:
            if section not in groups:
                lf = ttk.LabelFrame(parent, text=section, padding=8)
                lf.pack(fill="x", padx=6, pady=4)
                lf.columnconfigure(1, weight=1)
                groups[section] = [lf, 0]
            lf, row = groups[section]
            if kind == "bool":
                var = tk.BooleanVar()
                ttk.Checkbutton(lf, text=label, variable=var).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
            else:
                var = tk.StringVar()
                ttk.Label(lf, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
                if kind == "map":
                    w = ttk.Combobox(lf, textvariable=var, values=MAP_IDS)
                elif kind == "event":
                    w = ttk.Frame(lf)
                    ttk.Combobox(w, textvariable=var, values=EVENT_CHOICES, width=20).pack(side="left")
                    ttk.Button(w, text="Find event mod", command=self._find_event_mod).pack(side="left", padx=4)
                elif kind == "password":
                    w = ttk.Entry(lf, textvariable=var, show="•")
                    self.pw_entries.append(w)
                else:
                    w = ttk.Entry(lf, textvariable=var)
                if kind == "dir":
                    fr = ttk.Frame(lf)
                    fr.grid(row=row, column=1, sticky="ew", pady=2)
                    fr.columnconfigure(0, weight=1)
                    w.destroy()
                    w = ttk.Entry(fr, textvariable=var)
                    w.grid(row=0, column=0, sticky="ew")
                    ttk.Button(fr, text="Browse...", command=lambda v=var: self._browse_dir(v)).grid(row=0, column=1, padx=(4, 0))
                else:
                    w.grid(row=row, column=1, sticky="ew", pady=2)
            if hint:
                ttk.Label(lf, text=hint, style="Hint.TLabel", wraplength=260, justify="left").grid(
                    row=row, column=2, sticky="w", padx=(10, 0))
            groups[section][1] += 1
            self.form_vars[key] = var

    def _tab_server(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Server")
        sf = ScrollFrame(tab)
        sf.pack(fill="both", expand=True)
        self._build_fields(sf.inner, SERVER_FIELDS)
        bar = ttk.Frame(sf.inner)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Button(bar, text="Save server settings", command=lambda: self._save_form(),
                   style="Accent.TButton").pack(side="left")
        self.show_pw = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Show passwords", variable=self.show_pw, command=self._toggle_pw).pack(side="left", padx=10)
        ttk.Label(bar, text="Changes apply on the next (re)start.", style="Hint.TLabel").pack(side="left")
        lf = ttk.LabelFrame(sf.inner, text="Launch command (passwords hidden)", padding=8)
        lf.pack(fill="x", padx=6, pady=4)
        self.cmd_preview = tk.Text(lf, height=4, wrap="word", font=("Consolas", 9), relief="flat")
        self.cmd_preview.pack(fill="x")

    def _tab_cmdline(self):
        tab = ttk.Frame(self.nb)
        self.cmd_tab = tab
        self.nb.add(tab, text="Command line")
        sf = ScrollFrame(tab)
        sf.pack(fill="both", expand=True)
        body = sf.inner
        top = ttk.Frame(body)
        top.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Button(top, text="Save launch options", command=lambda: self._save_form(),
                   style="Accent.TButton").pack(side="right")
        intro = ttk.Label(top, text="Launch options for this server. Ticked options are added to the launch command "
                                    "(preview at the bottom). Changes apply on the next start.",
                          style="Hint.TLabel", wraplength=500, justify="left")
        intro.pack(side="left", fill="x", expand=True)
        top.bind("<Configure>", lambda e: intro.configure(wraplength=max(200, e.width - 190)), add="+")
        grid = ttk.Frame(body)
        grid.pack(fill="x")
        self._cmd_sections = []
        self._cmd_hints = []
        self.cmd_vars = {}

        def section(title):
            lf = ttk.LabelFrame(grid, text=title, padding=8)
            self._cmd_sections.append(lf)
            return lf

        # --- server platform & language
        lf = section("Players & language")
        self.cmd_platform = tk.StringVar()
        ttk.Label(lf, text="Who can join").grid(row=0, column=0, sticky="w")
        pf = ttk.Frame(lf)
        pf.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        for value, label in PLATFORM_CHOICES:
            ttk.Radiobutton(pf, text=label, variable=self.cmd_platform, value=value).pack(anchor="w")
        self.cmd_culture = tk.StringVar()
        ttk.Label(lf, text="Server language (-culture)").grid(row=2, column=0, sticky="w")
        ttk.Combobox(lf, textvariable=self.cmd_culture, values=CULTURES, width=12).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(lf, text="Blank = default (English). Changes server messages only, not players' game language.",
                  style="Hint.TLabel", wraplength=360, justify="left").grid(row=3, column=0, columnspan=2, sticky="w")

        # --- network
        lf = section("Network")
        self.cmd_public_ip = tk.StringVar()
        self.cmd_auto_ip = tk.BooleanVar()
        self.cmd_multihome = tk.StringVar()
        self.cmd_mh_rcon = tk.BooleanVar()
        ttk.Label(lf, text="Public IP shown in the server list (-PublicIPForEpic)").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Entry(lf, textvariable=self.cmd_public_ip, width=20).grid(row=1, column=0, sticky="w")
        ttk.Button(lf, text="Use my public IP", command=self._fill_public_ip).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Checkbutton(lf, text="Look it up automatically at every start (for changing home IPs)",
                        variable=self.cmd_auto_ip).grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 6))
        ttk.Label(lf, text="MultiHome - bind to one network address (PCs with several)").grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Entry(lf, textvariable=self.cmd_multihome, width=20).grid(row=4, column=0, sticky="w")
        ttk.Button(lf, text="Use local IP", command=lambda: self.cmd_multihome.set(local_ip())).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Checkbutton(lf, text="Use the MultiHome address for RCON too", variable=self.cmd_mh_rcon).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))
        ttk.Label(lf, text="Leave both blank on a normal home PC. Ports are on the Server tab.",
                  style="Hint.TLabel", wraplength=360, justify="left").grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- CPU
        lf = section("CPU performance")
        self.cmd_priority = tk.StringVar(value="Normal")
        ttk.Label(lf, text="Priority").grid(row=0, column=0, sticky="w")
        ttk.Combobox(lf, textvariable=self.cmd_priority, values=CPU_PRIORITIES, state="readonly", width=14).grid(
            row=0, column=1, sticky="w", padx=6)
        ttk.Label(lf, text="CPU cores").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.cmd_cores = []
        self.cmd_cores_lbl = ttk.Label(lf, text="")
        self.cmd_cores_lbl.grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Button(lf, text="Select CPU cores...", command=self._cores_dialog).grid(row=2, column=1, sticky="w", padx=6, pady=(2, 0))
        ttk.Label(lf, text="Applied to the running server straight away and at every start. Giving each map "
                           "its own cores stops a cluster fighting over the same ones. 'High' helps a busy server; "
                           "avoid it on a PC you also game on.", style="Hint.TLabel", wraplength=360,
                  justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # --- flag groups
        for title, items in CMD_FLAG_GROUPS:
            lf = section(title)
            for i, (flag, label, hint) in enumerate(items):
                v = tk.BooleanVar()
                self.cmd_vars[flag] = v
                ttk.Checkbutton(lf, text=label, variable=v).grid(row=i, column=0, sticky="nw")
                hl = ttk.Label(lf, text=hint or (flag if len(flag) <= 18 else ""), style="Hint.TLabel",
                               wraplength=170, justify="left")
                hl.grid(row=i, column=1, sticky="nw", padx=(10, 0))
                self._cmd_hints.append(hl)

        lf = section("Not included")
        ttk.Label(lf, text="Save-format conversion is left out on purpose - it can't be undone. Anything else "
                           "(colour events, new flags) can go in 'Extra -arguments' on the Server tab.",
                  style="Hint.TLabel", wraplength=360, justify="left").pack(anchor="w")

        prev = ttk.LabelFrame(body, text="Launch command (passwords hidden)", padding=8)
        prev.pack(fill="x", padx=6, pady=6)
        self.cmd_preview2 = tk.Text(prev, height=4, wrap="word", font=("Consolas", 9), relief="flat")
        self.cmd_preview2.pack(fill="x")
        self._cmd_cols = 0
        sf.canvas.bind("<Configure>", lambda e: self._grid_cmd_sections(3 if e.width >= 1250 else 2 if e.width >= 760 else 1),
                       add="+")
        self._grid_cmd_sections(2)
        self._cmd_grid = grid
        for var in [self.cmd_platform, self.cmd_culture, self.cmd_public_ip, self.cmd_auto_ip, self.cmd_multihome,
                    self.cmd_priority] + list(self.cmd_vars.values()):
            var.trace_add("write", lambda *_: self._preview_cmdline())

    def _grid_cmd_sections(self, cols):
        if cols == self._cmd_cols:
            return
        self._cmd_cols = cols
        parent = self._cmd_sections[0].master
        for c in range(3):
            parent.columnconfigure(c, weight=1 if c < cols else 0, uniform="cmd" if c < cols else "")
        for i, lf in enumerate(self._cmd_sections):
            lf.grid(row=i // cols, column=i % cols, sticky="nsew", padx=6, pady=4)
        for hl in self._cmd_hints:
            hl.configure(wraplength=420 if cols == 1 else 170)

    def _cmdline_values(self):
        return {"cmd_flags": [f for f, v in self.cmd_vars.items() if v.get()],
                "server_platform": self.cmd_platform.get().strip(), "culture": self.cmd_culture.get().strip(),
                "public_ip": self.cmd_public_ip.get().strip(), "auto_public_ip": self.cmd_auto_ip.get(),
                "multihome": self.cmd_multihome.get().strip(), "multihome_rcon": self.cmd_mh_rcon.get(),
                "cpu_priority": self.cmd_priority.get() or "Normal", "cpu_cores": list(self.cmd_cores)}

    def _load_cmdline(self, s):
        self._loading_cmd = True
        try:
            flags = set(s.get("cmd_flags", []))
            for f, v in self.cmd_vars.items():
                v.set(f in flags)
            self.cmd_platform.set(s.get("server_platform", ""))
            self.cmd_culture.set(s.get("culture", ""))
            self.cmd_public_ip.set(s.get("public_ip", ""))
            self.cmd_auto_ip.set(bool(s.get("auto_public_ip")))
            self.cmd_multihome.set(s.get("multihome", ""))
            self.cmd_mh_rcon.set(bool(s.get("multihome_rcon")))
            self.cmd_priority.set(s.get("cpu_priority") or "Normal")
            self.cmd_cores = list(s.get("cpu_cores") or [])
            self.cmd_cores_lbl.configure(text=describe_cores(self.cmd_cores))
        finally:
            self._loading_cmd = False
        self._preview_cmdline()

    def _validate_cmdline(self, vals):
        import ipaddress
        for key, label in (("public_ip", "Public IP"), ("multihome", "MultiHome address")):
            if vals[key]:
                try:
                    ipaddress.ip_address(vals[key])
                except ValueError:
                    raise ValueError(f"{label} '{vals[key]}' isn't a valid IP address.")
        if vals["server_platform"] and not re.fullmatch(r"[A-Za-z0-9+]+", vals["server_platform"]):
            raise ValueError("Server platform can only contain letters and '+', e.g. PC+XSX.")
        if vals["culture"] and not re.fullmatch(r"[A-Za-z_-]+", vals["culture"]):
            raise ValueError("Language code looks wrong, e.g. en or pt_BR.")

    def _preview_cmdline(self):
        s = self.current()
        if not s or getattr(self, "_loading_cmd", False) or not hasattr(self, "cmd_preview2"):
            return
        preview = dict(s)
        preview.update(self._cmdline_values())
        for key, var in self.form_vars.items():  # include unsaved Server-tab edits
            try:
                preview[key] = var.get() if isinstance(var, tk.BooleanVar) else var.get().strip()
            except tk.TclError:
                pass
        try:
            text = self.mgr.to_cmdline(self.mgr.build_command(preview, mask=True))
        except Exception as e:
            text = f"(can't build the command yet: {e})"
        self.cmd_preview2.configure(state="normal")
        self.cmd_preview2.delete("1.0", "end")
        self.cmd_preview2.insert("1.0", text)
        self.cmd_preview2.configure(state="disabled")

    def _fill_public_ip(self):
        def work():
            try:
                ip = public_ip()
                self.q.put(("call", None, lambda: self.cmd_public_ip.set(ip)))
            except Exception as e:
                self.q.put(("error", None, f"Couldn't look up your public IP:\n{e}"))
        threading.Thread(target=work, daemon=True).start()

    def _cores_dialog(self):
        total = os.cpu_count() or 1
        d = tk.Toplevel(self.root)
        d.title("Select CPU cores")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Pick which of this PC's {total} logical cores the server may use. Ticking none (or "
                           "all) means every core.", wraplength=460, justify="left").pack(anchor="w")
        g = ttk.Frame(fr)
        g.pack(anchor="w", pady=8)
        chosen = set(self.cmd_cores)
        vs = []
        per_row = 8
        for c in range(total):
            v = tk.BooleanVar(value=c in chosen)
            vs.append(v)
            ttk.Checkbutton(g, text=f"Core {c}", variable=v).grid(row=c // per_row, column=c % per_row, sticky="w", padx=(0, 8))
        bar = ttk.Frame(fr)
        bar.pack(fill="x")
        ttk.Button(bar, text="All", command=lambda: [v.set(True) for v in vs]).pack(side="left")
        ttk.Button(bar, text="None", command=lambda: [v.set(False) for v in vs]).pack(side="left", padx=4)
        ttk.Button(bar, text="First half", command=lambda: [v.set(i < total // 2) for i, v in enumerate(vs)]).pack(side="left")
        ttk.Button(bar, text="Second half", command=lambda: [v.set(i >= total // 2) for i, v in enumerate(vs)]).pack(side="left", padx=4)

        def ok():
            sel = [i for i, v in enumerate(vs) if v.get()]
            self.cmd_cores = [] if len(sel) in (0, total) else sel
            self.cmd_cores_lbl.configure(text=describe_cores(self.cmd_cores))
            self._preview_cmdline()
            d.destroy()

        bb = ttk.Frame(fr)
        bb.pack(fill="x", pady=(10, 0))
        ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bb, text="OK", command=ok).pack(side="right", padx=4)
        self.themed_window(d)

    def _tab_config(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Game settings")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Button(bar, text="Save to INI files", command=self._save_ini, style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Reload from disk", command=self._load_ini).pack(side="left", padx=4)
        self.ini_warn = ttk.Label(bar, text="", style="Warn.TLabel")
        self.ini_warn.pack(side="left", padx=10)
        self.ini_nb = ttk.Notebook(tab)
        self.ini_nb.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        common = ttk.Frame(self.ini_nb)
        self.ini_nb.add(common, text="Common settings")
        sf = ScrollFrame(common)
        sf.pack(fill="both", expand=True)
        ttk.Label(sf.inner, text="Leave a field blank to use ARK's default. Values are written to "
                                 "GameUserSettings.ini / Game.ini.", style="Hint.TLabel").pack(anchor="w", padx=8, pady=4)
        self._common_rows = []  # (label, widget, hint) per setting, regridded into 1 or 2 columns to fit
        for group, items in COMMON_SETTINGS:
            lf = ttk.LabelFrame(sf.inner, text=group, padding=8)
            lf.pack(fill="x", padx=6, pady=4)
            group_rows = []
            for fname, section, key, label, hint, kind in items:
                var = tk.StringVar()
                lab = ttk.Label(lf, text=label)
                if kind == "bool":
                    w = ttk.Combobox(lf, textvariable=var, values=["", "True", "False"], width=10, state="readonly")
                else:
                    w = ttk.Entry(lf, textvariable=var, width=30 if kind == "text" else 10)
                hl = ttk.Label(lf, text=hint, style="Hint.TLabel")
                group_rows.append((lab, w, hl))
                self.common_vars[(fname, section, key)] = var
            self._common_rows.append(group_rows)
        self._common_cols = 0
        self._grid_common(2)
        sf.update_idletasks()
        self._common_two_col_width = max(r[0][0].master.winfo_reqwidth() for r in self._common_rows) + 30
        sf.canvas.bind("<Configure>", lambda e: self._grid_common(2 if e.width >= self._common_two_col_width else 1),
                       add="+")

        for fname in (GUS, GINI):
            fr = ttk.Frame(self.ini_nb)
            self.ini_nb.add(fr, text=fname)
            txt = tk.Text(fr, wrap="none", undo=True, font=("Consolas", 10), height=5, width=40)
            ys = ttk.Scrollbar(fr, orient="vertical", command=txt.yview)
            xs = ttk.Scrollbar(fr, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
            ys.pack(side="right", fill="y")
            xs.pack(side="bottom", fill="x")
            txt.pack(fill="both", expand=True)
            self.ini_texts[fname] = txt
        self.ini_nb.bind("<<NotebookTabChanged>>", self._ini_tab_changed)

    def _tab_mods(self):
        tab = ttk.Frame(self.nb)
        self.mods_tab = tab
        self.nb.add(tab, text="Mods")
        bar = FlowFrame(tab, gap=6)
        bar.pack(fill="x", padx=6, pady=6)
        self.mod_query = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.mod_query, width=28)
        e.bind("<Return>", lambda ev: self._mod_search())
        self.mod_sort = tk.StringVar(value=CF_SORTS[0][0])
        cb = ttk.Combobox(bar, textvariable=self.mod_sort, values=[x[0] for x in CF_SORTS], width=15, state="readonly")
        cb.bind("<<ComboboxSelected>>", lambda ev: self._mod_search())
        self.mod_status = ttk.Label(bar, text="", style="Hint.TLabel")
        for w in (ttk.Label(bar, text="Search CurseForge:"), e, ttk.Label(bar, text="Sort:"), cb,
                  ttk.Button(bar, text="Search", command=self._mod_search),
                  ttk.Button(bar, text="Add by ID...", command=self._mod_add_by_id), self.mod_status):
            bar.add(w)
        self._mod_bar = bar

        pw = ttk.PanedWindow(tab, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        left = ttk.LabelFrame(pw, text="Search results", padding=6)
        pw.add(left, weight=1)
        cols = ("author", "downloads", "updated")
        self.mtree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="extended", height=3)
        self.mtree.heading("#0", text="Mod")
        self.mtree.heading("author", text="Author")
        self.mtree.heading("downloads", text="Downloads")
        self.mtree.heading("updated", text="Updated")
        self.mtree.column("#0", width=200, minwidth=100)
        self.mtree.column("author", width=90, minwidth=50)
        # Date and ID widths come from the text, so they still fit when Windows display scaling makes it bigger
        font = tkfont.nametofont("TkDefaultFont")
        date_w, id_w = font.measure("2026-10-30") + 16, font.measure("0000000") + 16
        self.mtree.column("downloads", width=max(72, font.measure("Downloads") + 16), minwidth=50, anchor="e", stretch=False)
        self.mtree.column("updated", width=date_w, minwidth=date_w, anchor="center", stretch=False)
        self.mtree.tag_configure("installed", foreground=self.colors["good"])
        ms = ttk.Scrollbar(left, orient="vertical", command=self.mtree.yview)
        self.mtree.configure(yscrollcommand=ms.set)
        mb = FlowFrame(left)
        mb.pack(side="bottom", fill="x", pady=(4, 0))
        mb.add(ttk.Button(mb, text="Install", command=lambda: self._mod_install(False), style="Accent.TButton"))
        mb.add(ttk.Button(mb, text="Install on cluster", command=lambda: self._mod_install(True)))
        mb.add(ttk.Button(mb, text="Open page", command=lambda: self._mod_open(self.mtree)))
        self.mod_more_btn = mb.add(ttk.Button(mb, text="Load more", command=lambda: self._mod_search(more=True),
                                              state="disabled"))
        ms.pack(side="right", fill="y")
        self.mtree.pack(fill="both", expand=True)
        self.mtree.bind("<<TreeviewSelect>>", lambda ev: self._mod_show_details(self.mtree))
        self.mtree.bind("<Double-1>", lambda ev: self._mod_install(False))

        right = ttk.Frame(pw)
        pw.add(right, weight=1)
        initial_sash(pw, 0.58)
        mod_hint = ttk.Label(right, text="The server downloads and updates its mods automatically when it starts, "
                                         "so restart it after adding, removing or switching mods. "
                                         "A passive mod keeps its data but has its features off.",
                             style="Hint.TLabel", wraplength=300, justify="left")
        mod_hint.pack(side="bottom", anchor="w", pady=(6, 0))
        right.bind("<Configure>", lambda e: mod_hint.configure(wraplength=max(120, e.width - 8)), add="+")
        df = ttk.LabelFrame(right, text="Details", padding=6)
        df.pack(fill="x")
        self.mod_details = tk.Text(df, height=5, width=30, wrap="word", font=("Segoe UI", 9), relief="flat", state="disabled")
        self.mod_details.pack(fill="x")
        inf = ttk.LabelFrame(right, text="Installed on this server (load order)", padding=6)
        inf.pack(fill="both", expand=True, pady=(6, 0))
        self.itree = ttk.Treeview(inf, columns=("name", "id", "updated"), show="tree headings", selectmode="browse",
                                  height=3, style="Mods.Treeview")
        self._mod_mode_layout()
        self.itree.heading("name", text="Mod", anchor="w")
        self.itree.column("name", width=150, minwidth=80)
        self.itree.tag_configure("passive", foreground=self.colors["muted"])
        self.itree.heading("id", text="ID")
        self.itree.heading("updated", text="Updated")
        self.itree.column("id", width=id_w, minwidth=id_w, anchor="center", stretch=False)
        self.itree.column("updated", width=date_w, minwidth=date_w, anchor="center", stretch=False)
        ib = FlowFrame(inf)
        ib.pack(side="bottom", fill="x", pady=(4, 0))
        for text, cmd in [("Remove", self._mod_remove),
                          ("Up", lambda: self._mod_move(-1)),
                          ("Down", lambda: self._mod_move(1)), ("Open page", lambda: self._mod_open(self.itree)),
                          ("Refresh", lambda: self._mod_fetch_info(force=True))]:
            ib.add(ttk.Button(ib, text=text, command=cmd))
        self.itree.pack(fill="both", expand=True)
        self.itree.bind("<<TreeviewSelect>>", lambda ev: self._mod_show_details(self.itree))
        self.itree.bind("<ButtonRelease-1>", self._mod_mode_cell_click, add="+")

    # ---- mods ---------------------------------------------------------------------
    def _mod_ids(self, s):
        return [m for m in s.get("mods", "").split(",") if m.strip()]

    def _passive_ids(self, s):
        return [m.strip() for m in s.get("passive_mods", "").split(",") if m.strip()]

    def _set_mod_ids(self, s, ids):
        s["mods"] = ",".join(dict.fromkeys(i.strip() for i in ids if i.strip()))
        keep = set(self._mod_ids(s))  # a removed mod can't stay passive
        s["passive_mods"] = ",".join(m for m in self._passive_ids(s) if m in keep)
        if s is self.current() and "mods" in self.form_vars:
            self.form_vars["mods"].set(s["mods"])

    def _mod_info(self, mid):
        return self.mod_results.get(mid) or self.cfg.data.setdefault("mod_cache", {}).get(mid)

    def _mod_search(self, more=False):
        text, sort = self.mod_query.get(), self.mod_sort.get()
        index = len(self.mtree.get_children()) if more else 0
        if not more:
            self.mtree.delete(*self.mtree.get_children())
            self.mod_results.clear()
        self.mod_status.configure(text="Searching" + (" (via free proxy)" if self.cf.using_proxy() else "") + "...")
        self.mod_more_btn.configure(state="disabled")
        token = object()
        self._mod_search_token = token

        def work():
            try:
                mods, total = self.cf.search(text, sort, index)
                self.q.put(("call", None, lambda: self._mod_show_results(token, mods, total)))
            except Exception as e:
                msg = str(e)
                self.q.put(("call", None, lambda: self._mod_search_failed(token, msg)))

        threading.Thread(target=work, daemon=True).start()

    def _mod_search_failed(self, token, msg):
        if token is self._mod_search_token:
            self.mod_status.configure(text="Search failed")
            messagebox.showerror(APP_NAME, msg)

    def _mod_show_results(self, token, mods, total):
        if token is not self._mod_search_token:
            return
        s = self.current()
        installed = set(self._mod_ids(s)) if s else set()
        cache = self.cfg.data.setdefault("mod_cache", {})
        for m in mods:
            if self.mtree.exists(m["id"]):
                continue
            self.mod_results[m["id"]] = m
            if m["id"] in cache:
                cache[m["id"]] = m
            self.mtree.insert("", "end", iid=m["id"], text=("✓ " if m["id"] in installed else "") + m["name"],
                              values=(m["author"], short_number(m["downloads"]), m["updated"]),
                              tags=("installed",) if m["id"] in installed else ())
        shown = len(self.mtree.get_children())
        self.mod_status.configure(text=f"Showing {shown} of {total} mods"
                                  + (" (via free proxy - your API key was rejected)" if self.cf.key_problem else ""))
        if self.cf.key_problem and self.cf.key_problem != getattr(self, "_cf_warned", None):
            self._cf_warned = self.cf.key_problem
            messagebox.showwarning(APP_NAME, self.cf.key_problem)
        self._mod_bar.relayout()
        self.mod_more_btn.configure(state="normal" if shown < min(total, 10000) and mods else "disabled")

    def _mod_show_details(self, tree):
        sel = tree.selection()
        if not sel:
            return
        m = self._mod_info(sel[0])
        self.mod_details.configure(state="normal")
        self.mod_details.delete("1.0", "end")
        if m:
            cats = ", ".join(c for c in m.get("categories", []) if c)
            self.mod_details.insert("1.0", f"{m['name']}  (ID {m['id']})\n"
                                           f"By {m.get('author') or '?'} · {short_number(m.get('downloads', 0))} downloads"
                                           f" · updated {m.get('updated') or '?'}\n"
                                           + (f"Categories: {cats}\n" if cats else "")
                                           + f"\n{m.get('summary', '')}")
        else:
            self.mod_details.insert("1.0", f"Mod ID {sel[0]}\n\nNo details loaded yet - click 'Refresh info'.")
        self.mod_details.configure(state="disabled")

    def _mod_targets(self, cluster):
        s = self.current()
        if not s:
            return []
        if not cluster:
            return [s]
        targets = [o for o in self.cfg.servers if o.get("cluster")]
        if s not in targets:
            targets.insert(0, s)
        return targets

    def _mod_install(self, cluster=False, ids=None):
        if not self._save_form(silent=True):
            return
        ids = ids or list(self.mtree.selection())
        if not ids:
            messagebox.showinfo(APP_NAME, "Select one or more mods in the search results first.")
            return
        targets = self._mod_targets(cluster)
        if cluster and len(targets) == 1 and not targets[0].get("cluster"):
            messagebox.showinfo(APP_NAME, "No servers have 'Join the cluster' ticked - installing on this server only.")
        cache = self.cfg.data.setdefault("mod_cache", {})
        added = 0
        for t in targets:
            cur = self._mod_ids(t)
            new = [i for i in ids if i not in cur]
            added += len(new)
            self._set_mod_ids(t, cur + new)
        for i in ids:
            if i in self.mod_results:
                cache[i] = self.mod_results[i]
        self.cfg.save()
        names = ", ".join(self._mod_info(i)["name"] if self._mod_info(i) else i for i in ids)
        for t in targets:
            self.mgr.log(t, f"Mod(s) added: {names}")
        self._refresh_installed_mods()
        self._refresh_mod_marks()
        self._update_cmd_preview()
        if not added:
            self.mod_status.configure(text="Already installed")
            return
        is_map = any("map" in " ".join(self._mod_info(i).get("categories", [])).lower()
                     for i in ids if self._mod_info(i))
        msg = f"Added {names} to {', '.join(t['name'] for t in targets)}."
        if is_map:
            msg += ("\n\nThis looks like a map mod. Set the Map field on the Server tab to the map name given on "
                    "the mod's page.")
        running = [t for t in targets if self.mgr.is_running(t)]
        if running:
            if messagebox.askyesno(APP_NAME, msg + "\n\nThe server downloads mods when it starts. Restart "
                                                   f"{len(running)} running server(s) now (players get countdown warnings)?"):
                for t in running:
                    try:
                        warns = parse_minutes(t.get("restart_warn_minutes", "")) or [5, 1]
                    except ValueError:
                        warns = [5, 1]
                    self.mgr.run_op(t, "Restarting", self.mgr.op_restart, False, warns, None, "Mod install")
        else:
            messagebox.showinfo(APP_NAME, msg + "\n\nThe mods download automatically the next time the server starts.")

    def _mod_add_by_id(self):
        raw = simpledialog.askstring(APP_NAME, "CurseForge mod ID (the 'Project ID' on the mod's page).\n"
                                               "Separate several with commas:", parent=self.root)
        if not raw:
            return
        ids = [x.strip() for x in raw.split(",") if x.strip()]
        if any(not x.isdigit() for x in ids):
            messagebox.showerror(APP_NAME, "Mod IDs are numbers, e.g. 928988.")
            return
        self._mod_install(False, ids)
        self._mod_fetch_info()

    def _mod_mode_layout(self):
        """Size the Active / Passive column and draw its circles right under the heading words.

        A Treeview can only show pictures in its first column, so one picture holds both circles. The heading
        is centred, and headings are padded evenly in every theme, so the words' centres can be worked out.
        Rows aren't: the theme may start them a few pixels in, so the picture allows for that. Rerun when the
        theme changes.
        """
        font = tkfont.nametofont("TkHeadingFont")
        word_a, word_p, space = font.measure("Active"), font.measure("Passive"), font.measure(" ")
        width = max(word_p + 12, 44) * 2 + 10
        gap = max(2, round((width / 2 - word_p) / space))
        text_w = word_a + gap * space + word_p
        left = (width - text_w) / 2
        self.mod_centres = (left + word_a / 2, left + text_w - word_p / 2)  # from the column's left edge
        pad = self.root.tk.splitlist(ttk.Style(self.root).lookup("Treeview.Item", "padding"))  # text or a list
        self.mod_row_pad = round(self.root.winfo_fpixels(str(pad[0]))) if pad else 0
        self.mod_images = mod_mode_images(width - self.mod_row_pad, [c - self.mod_row_pad for c in self.mod_centres])
        self.itree.heading("#0", anchor="center", text="Active" + " " * gap + "Passive")
        self.itree.column("#0", width=width, minwidth=width, stretch=False)

    def _mod_mode_cell_click(self, ev):
        # Left of the middle is Active, right of it Passive. Clicking the ticked circle does nothing.
        if self.itree.identify_column(ev.x) != "#0" or self.itree.identify_region(ev.x, ev.y) != "tree":
            return
        mid = self.itree.identify_row(ev.y)
        if mid and self.current():
            x0 = self.itree.bbox(mid, "#0")[0] if self.itree.bbox(mid, "#0") else 0
            self._mod_set_passive(mid, ev.x - x0 >= sum(self.mod_centres) / 2)

    def _mod_toggle_passive(self):
        s = self.current()
        sel = self.itree.selection()
        if s and sel:
            self._mod_set_passive(sel[0], sel[0] not in self._passive_ids(s))

    def _mod_set_passive(self, mid, make_passive):
        s = self.current()
        if not s or mid not in self._mod_ids(s):
            return
        passive = self._passive_ids(s)
        if (mid in passive) == make_passive:
            return
        if not self._save_form(silent=True):
            return
        info = self._mod_info(mid)
        name = info["name"] if info else mid
        if make_passive:
            passive.append(mid)
            msg = f"{name} is now passive (installed, data kept, features off) from the next start."
        else:
            passive.remove(mid)
            msg = f"{name} will be fully active again from the next start."
        s["passive_mods"] = ",".join(passive)
        self.cfg.save()
        self.mgr.log(s, msg)
        self._refresh_installed_mods()
        self.itree.selection_set(mid)
        self.itree.see(mid)
        self._update_cmd_preview()

    def _mod_remove(self):
        s = self.current()
        sel = self.itree.selection()
        if not s or not sel:
            return
        mid = sel[0]
        info = self._mod_info(mid)
        if not messagebox.askyesno(APP_NAME, f"Remove {info['name'] if info else mid} from {s['name']}?\n\n"
                                             "Items and creatures from this mod will be lost in-game for "
                                             "anyone who has them."):
            return
        if not self._save_form(silent=True):
            return
        self._set_mod_ids(s, [i for i in self._mod_ids(s) if i != mid])
        self.cfg.save()
        self.mgr.log(s, f"Mod removed: {info['name'] if info else mid} (restart to apply)")
        self._refresh_installed_mods()
        self._refresh_mod_marks()
        self._update_cmd_preview()

    def _mod_move(self, delta):
        s = self.current()
        sel = self.itree.selection()
        if not s or not sel or not self._save_form(silent=True):
            return
        ids = self._mod_ids(s)
        i = ids.index(sel[0]) if sel[0] in ids else -1
        j = i + delta
        if i < 0 or not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        self._set_mod_ids(s, ids)
        self.cfg.save()
        self._refresh_installed_mods()
        self.itree.selection_set(sel[0])
        self._update_cmd_preview()

    def _mod_open(self, tree):
        sel = tree.selection()
        if not sel:
            return
        m = self._mod_info(sel[0])
        webbrowser.open(m["url"] if m and m.get("url") else
                        f"https://www.curseforge.com/ark-survival-ascended/search?search={sel[0]}")

    def _refresh_mod_marks(self):
        s = self.current()
        installed = set(self._mod_ids(s)) if s else set()
        for iid in self.mtree.get_children():
            m = self.mod_results.get(iid)
            if m:
                on = iid in installed
                self.mtree.item(iid, text=("✓ " if on else "") + m["name"], tags=("installed",) if on else ())

    def _refresh_installed_mods(self):
        self.itree.delete(*self.itree.get_children())
        s = self.current()
        if not s:
            return
        missing = []
        for mid in self._mod_ids(s):
            m = self._mod_info(mid)
            if not m:
                missing.append(mid)
            passive = mid in self._passive_ids(s)
            name = m["name"] if m else ("(name not found - click Refresh)" if mid in self._mod_fetch_failed
                                        else "(loading...)")
            self.itree.insert("", "end", iid=mid, image=self.mod_images[passive],
                              values=(name, mid, m.get("updated", "") if m else ""),
                              tags=("passive",) if passive else ())
        if missing:
            self._mod_fetch_info()

    def _mod_fetch_info(self, force=False):
        s = self.current()
        if not s:
            return
        cache = self.cfg.data.setdefault("mod_cache", {})
        ids = [i for i in self._mod_ids(s) if force or (i not in cache and i not in self._mod_fetch_tried)]
        if not ids:
            return
        self._mod_fetch_tried.update(ids)
        self._mod_fetch_failed.difference_update(ids)

        def work():
            try:
                mods = self.cf.get_mods(ids)
            except Exception as e:
                msg = str(e)

                def failed():  # say so on the row instead of "(loading...)" forever, and why in the Log tab
                    self._mod_fetch_failed.update(ids)
                    self.mgr.log(s, f"Couldn't load the names of {len(ids)} mod(s) from CurseForge: {msg.splitlines()[0]}")
                    self._refresh_installed_mods()
                    if force:
                        messagebox.showerror(APP_NAME, msg)
                self.q.put(("call", None, failed))
                return

            def done():
                for m in mods:
                    cache[m["id"]] = m
                self._mod_fetch_failed.update(i for i in ids if i not in cache)  # CurseForge doesn't know these
                self.cfg.save()
                self._refresh_installed_mods()

            self.q.put(("call", None, done))

        threading.Thread(target=work, daemon=True).start()

    def _grid_common(self, cols):
        if cols == self._common_cols:
            return
        self._common_cols = cols
        for group_rows in self._common_rows:
            for i, (lab, w, hl) in enumerate(group_rows):
                r, c = divmod(i, cols)
                lab.grid(row=r, column=c * 3, sticky="w", padx=(0, 6), pady=2)
                w.grid(row=r, column=c * 3 + 1, sticky="w", pady=2)
                hl.grid(row=r, column=c * 3 + 2, sticky="w", padx=(4, 18))

    def _tab_plugins(self):
        tab = ttk.Frame(self.nb)
        self.plugins_tab = tab
        self.nb.add(tab, text="Plugins")
        api = ttk.LabelFrame(tab, text="AsaApi - server plugin framework", padding=8)
        api.pack(fill="x", padx=6, pady=(6, 4))
        row = ttk.Frame(api)
        row.pack(fill="x")
        self.api_status = ttk.Label(row, text="", style="Status.TLabel")
        self.api_status.pack(side="left")
        self.api_latest = ttk.Label(row, text="", style="Hint.TLabel")
        self.api_latest.pack(side="left", padx=10)
        v = tk.BooleanVar()
        self.form_vars["asaapi"] = v
        ttk.Checkbutton(api, text="Start this server with AsaApi (plugins on) - launches it through AsaApiLoader.exe",
                        variable=v, command=lambda: self._save_form()).pack(anchor="w", pady=(6, 2))
        bar = FlowFrame(api)
        bar.pack(fill="x", pady=(4, 0))
        for text, cmd in [("Install / update AsaApi", lambda: self._api_install()),
                          ("Install from .zip...", lambda: self._api_install(from_zip=True)),
                          ("Check for update", self._api_check), ("Install on all servers", self._api_install_all),
                          ("Remove AsaApi", self._api_remove), ("AsaApi settings", self._api_open_config),
                          ("API logs", lambda: self._api_open("logs")), ("Find plugins online", lambda: webbrowser.open(ASAAPI_SITE))]:
            bar.add(ttk.Button(bar, text=text, command=cmd))
        note = ttk.Label(api, text="AsaApi is a community project (ark-server-api.com), not made by Studio Wildcard. After an "
                            "ARK update, AsaApi and plugins sometimes need updating too - if the server stops starting "
                            "after an update, untick the box above until they catch up. Installing needs the server stopped.",
                  style="Hint.TLabel", wraplength=600, justify="left")
        note.pack(anchor="w", fill="x", pady=(6, 0))
        api.bind("<Configure>", lambda e: note.configure(wraplength=max(250, e.width - 30)), add="+")

        lf = ttk.LabelFrame(tab, text="Plugins", padding=6)
        lf.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        pb = FlowFrame(lf)
        pb.pack(side="bottom", fill="x", pady=(4, 0))
        for text, cmd in [("Install plugin (.zip)...", self._plugin_install),
                          ("Plugins folder", lambda: self._api_open("plugins")), ("Enable / disable", self._plugin_toggle),
                          ("Edit config", self._plugin_config), ("Selected plugin's folder", self._plugin_folder),
                          ("Reload now", self._plugin_reload), ("Remove", self._plugin_remove),
                          ("Refresh", self._refresh_plugins)]:
            pb.add(ttk.Button(pb, text=text, command=cmd))
        self.plugin_tree = ttk.Treeview(lf, columns=("version", "state", "config", "desc"), show="tree headings",
                                        selectmode="browse", height=3)
        for c, label, w, st in [("#0", "Plugin", 180, True), ("version", "Version", 70, False),
                                ("state", "State", 80, False), ("config", "Config", 60, False),
                                ("desc", "Description", 320, True)]:
            self.plugin_tree.heading(c, text=label, anchor="w")
            self.plugin_tree.column(c, width=w, minwidth=50, stretch=st)
        self.plugin_tree.tag_configure("off", foreground=self.colors["off"])
        self.plugin_tree.tag_configure("bad", foreground=self.colors["bad"])
        self.plugin_tree.pack(fill="both", expand=True)
        self.plugin_tree.bind("<Double-1>", lambda e: self._plugin_config())
        self._api_latest_tag = None

    def _refresh_plugins(self):
        if not hasattr(self, "plugin_tree"):
            return
        s = self.current()
        self.plugin_tree.delete(*self.plugin_tree.get_children())
        if not s:
            return
        st = asaapi_status(s)
        if st["installed"]:
            ver = st["version"] or "installed manually"
            text, col = f"AsaApi {ver}", self.colors["good"]
        elif st["loader"] or st["dll"]:
            text, col = "AsaApi files incomplete - reinstall", self.colors["bad"]
        else:
            text, col = "AsaApi not installed", self.colors["muted"]
        self.api_status.configure(text=text, foreground=col)
        if self._api_latest_tag:
            newer = st["installed"] and st["version"] and st["version"] != self._api_latest_tag
            self.api_latest.configure(text=f"Latest: {self._api_latest_tag}" + (" - update available" if newer else ""))
        for pl in list_plugins(s):
            state = "Enabled" if pl["enabled"] else "Disabled"
            if not pl["has_dll"]:
                state = "No .dll!"
            self.plugin_tree.insert("", "end", iid=pl["dir"], text=pl["full_name"] if pl["full_name"] != pl["name"]
                                    else pl["name"], values=(pl["version"], state, "yes" if pl["has_config"] else "-",
                                                            pl["description"]),
                                    tags=("bad",) if not pl["has_dll"] else () if pl["enabled"] else ("off",))

    def _api_needs_stopped(self, s, what):
        if self.mgr.is_running(s):
            messagebox.showinfo(APP_NAME, f"Stop {s['name']} before you {what} - the server keeps these files locked "
                                          "while it runs.")
            return True
        return False

    def _api_install(self, from_zip=False, servers=None):
        s = self._need()
        if not s:
            return
        targets = servers or [s]
        for t in targets:
            if not self.mgr.is_installed(t):
                messagebox.showinfo(APP_NAME, f"Install the server files for {t['name']} first.")
                return
            if servers is None and self._api_needs_stopped(t, "install AsaApi"):
                return
        zip_path = None
        if from_zip:
            zip_path = filedialog.askopenfilename(title="AsaApi release zip", filetypes=[("Zip files", "*.zip")])
            if not zip_path:
                return

        def op(t):
            if zip_path:
                version = os.path.splitext(os.path.basename(zip_path))[0]
                asaapi_install_zip(t, zip_path, version, lambda m: self.mgr.log(t, m))
                return
            tag, url, name = asaapi_latest()
            dl = os.path.join(DATA_DIR, "downloads", name)
            if not os.path.isfile(dl):
                self.mgr.log(t, f"Downloading AsaApi {tag}...")
                os.makedirs(os.path.dirname(dl), exist_ok=True)
                req = urllib.request.Request(url, headers={"User-Agent": f"Tamer/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=120) as r, open(dl + ".partial", "wb") as f:
                    shutil.copyfileobj(r, f)
                os.replace(dl + ".partial", dl)
            asaapi_install_zip(t, dl, tag, lambda m: self.mgr.log(t, m))
            self._api_latest_tag = tag

        done_names = []
        for t in targets:
            if servers is not None and self.mgr.is_running(t):
                self.mgr.log(t, "AsaApi: skipped - the server is running.")
                continue
            done_names.append(t["name"])
            self.mgr.run_op(t, "Installing AsaApi", lambda srv: (op(srv), self.q.put(("call", None, self._refresh_plugins))))
        if done_names:
            self.nb.select(self.log_tab) if len(targets) == 1 else None
            if not s.get("asaapi") and len(targets) == 1:
                self.mgr.log(s, "Tip: tick 'Start this server with AsaApi' on the Plugins tab to use it.")

    def _api_install_all(self):
        installed = [x for x in self.cfg.servers if self.mgr.is_installed(x)]
        seen, unique = set(), []
        for x in installed:  # one install per server folder
            key = os.path.normcase(os.path.normpath(x["install_dir"]))
            if key not in seen:
                seen.add(key)
                unique.append(x)
        running = [x["name"] for x in unique if self.mgr.is_running(x)]
        msg = f"Install or update AsaApi on {len(unique)} server folder(s)?"
        if running:
            msg += f"\n\nRunning servers are skipped: {', '.join(running)}"
        if unique and messagebox.askyesno(APP_NAME, msg):
            self._api_install(servers=unique)

    def _api_check(self):
        def work():
            try:
                tag, _u, _n = asaapi_latest()
                self._api_latest_tag = tag
                self.q.put(("call", None, self._refresh_plugins))
            except Exception as e:
                self.q.put(("error", None, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _api_remove(self):
        s = self._need()
        if not s or self._api_needs_stopped(s, "remove AsaApi"):
            return
        if not messagebox.askyesno(APP_NAME, f"Remove AsaApi from {s['name']}? Your plugins and settings are kept, "
                                             "so reinstalling later brings them back."):
            return
        asaapi_remove(s, lambda m: self.mgr.log(s, m))
        if s.get("asaapi"):
            self.form_vars["asaapi"].set(False)
            self._save_form()
        self._refresh_plugins()

    def _api_open(self, key):
        s = self.current()
        if s:
            path = asaapi_paths(s)[key]
            if not os.path.exists(path):
                tip = ("Install AsaApi first with the button above." if key == "plugins"
                       else "Start the server with AsaApi once.")
                messagebox.showinfo(APP_NAME, f"Doesn't exist yet:\n{path}\n\n({tip})")
                return
            open_path(path)

    def _api_open_config(self):
        s = self.current()
        if s:
            path = asaapi_paths(s)["config"]
            if not os.path.isfile(path):
                messagebox.showinfo(APP_NAME, "AsaApi's config.json appears after you install AsaApi.")
                return
            open_path(path)

    def _selected_plugin(self):
        sel = self.plugin_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a plugin first.")
            return None
        return sel[0]

    def _plugin_install(self):
        s = self._need()
        if not s:
            return
        if not asaapi_status(s)["installed"] and not messagebox.askyesno(
                APP_NAME, "AsaApi isn't installed on this server yet, so plugins won't load. Install the plugin anyway?"):
            return
        paths = filedialog.askopenfilenames(title="Plugin zip file(s)", filetypes=[("Zip files", "*.zip")])
        if not paths:
            return
        names, errors = [], []
        for zp in paths:
            try:
                names += install_plugin_zip(s, zp, lambda m: self.mgr.log(s, m))
            except Exception as e:
                errors.append(f"{os.path.basename(zp)}: {e}")
        self._refresh_plugins()
        msg = (f"Installed: {', '.join(names)}." if names else "") + ("\n\nProblems:\n" + "\n".join(errors) if errors else "")
        if names and self.mgr.runtime(s["id"]).online:
            msg += "\n\nUse 'Reload now' to load it without a restart, or restart the server."
        elif names:
            msg += "\n\nIt loads the next time the server starts with AsaApi."
        (messagebox.showerror if errors and not names else messagebox.showinfo)(APP_NAME, msg.strip())

    def _plugin_toggle(self):
        s, d = self.current(), self._selected_plugin()
        if not s or not d:
            return
        name = os.path.basename(d)
        enabled = os.path.basename(os.path.dirname(d)) == "Plugins"
        if self.mgr.runtime(s["id"]).online and enabled:
            self.mgr.try_rcon(s, f"plugins.unload {name}")
        try:
            set_plugin_enabled(s, name, not enabled)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Couldn't move the plugin (the server may still have it loaded):\n{e}")
            return
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        if self.mgr.runtime(s["id"]).online and not enabled:
            self.mgr.try_rcon(s, f"plugins.load {name}")
        self.mgr.log(s, f"Plugin {name} {'disabled' if enabled else 'enabled'}.")
        self._refresh_plugins()

    def _plugin_config(self):
        d = self._selected_plugin()
        if d:
            cfgp = os.path.join(d, "config.json")
            open_path(cfgp if os.path.isfile(cfgp) else d)

    def _plugin_folder(self):
        d = self._selected_plugin()
        if d:
            open_path(d)

    def _plugin_reload(self):
        s, d = self.current(), self._selected_plugin()
        if not s or not d:
            return
        if not self.mgr.runtime(s["id"]).online:
            messagebox.showinfo(APP_NAME, "The server isn't online - plugins load automatically at the next start.")
            return
        name = os.path.basename(d)

        def work():
            a = self.mgr.try_rcon(s, f"plugins.unload {name}")
            b = self.mgr.try_rcon(s, f"plugins.load {name}")
            self.mgr.log(s, f"Plugin {name} reloaded: {(b or a or 'no reply').strip()[:150]}")
            self.q.put(("info", None, f"Reload sent for {name}:\n{(b or a or 'no reply - is AsaApi running?').strip()[:300]}"))
        threading.Thread(target=work, daemon=True).start()

    def _plugin_remove(self):
        s, d = self.current(), self._selected_plugin()
        if not s or not d:
            return
        name = os.path.basename(d)
        if not messagebox.askyesno(APP_NAME, f"Delete the {name} plugin, including its config.json?"):
            return
        if self.mgr.runtime(s["id"]).online:
            self.mgr.try_rcon(s, f"plugins.unload {name}")
        try:
            shutil.rmtree(d)
            self.mgr.log(s, f"Plugin {name} removed.")
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Couldn't delete it (stop the server first):\n{e}")
        self._refresh_plugins()

    def _tab_rcon(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Players")
        pw = ttk.PanedWindow(tab, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6, pady=6)
        initial_sash(pw, 0.38)

        pl = ttk.LabelFrame(pw, text="Online players", padding=6)
        pw.add(pl, weight=1)
        self.ptree = ttk.Treeview(pl, columns=("name", "id"), show="headings", selectmode="browse", height=3)
        self.ptree.heading("name", text="Name")
        self.ptree.heading("id", text="Player ID (EOS)")
        self.ptree.column("name", width=120, minwidth=60)
        self.ptree.column("id", width=170, minwidth=60)
        pb = FlowFrame(pl)
        pb.pack(side="bottom", fill="x", pady=(4, 0))
        self.ptree.pack(fill="both", expand=True)
        for text, cmd in [("Refresh", lambda: self._rcon_send("ListPlayers")),
                          ("Kick", lambda: self._player_action("KickPlayer")),
                          ("Ban", lambda: self._player_action("BanPlayer")), ("Copy ID", self._copy_player_id)]:
            pb.add(ttk.Button(pb, text=text, command=cmd))

        cf = ttk.LabelFrame(pw, text="Console (in-game chat appears here too)", padding=6)
        pw.add(cf, weight=2)
        quick = FlowFrame(cf)
        quick.pack(fill="x", pady=(0, 4))
        for text, cmd in [("Save world", lambda: self._rcon_send("SaveWorld")),
                          ("Broadcast...", lambda: self._rcon_prompt("Broadcast", "Broadcast message:")),
                          ("Chat...", lambda: self._rcon_prompt("ServerChat", "Chat message:")),
                          ("Wipe wild dinos", self._destroy_wild), ("Clear", lambda: self._clear_console())]:
            quick.add(ttk.Button(quick, text=text, command=cmd))
        self.console = tk.Text(cf, height=3, width=30, wrap="word", font=("Consolas", 10), state="disabled")
        cs = ttk.Scrollbar(cf, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=cs.set)
        ent = ttk.Frame(cf)
        ent.pack(side="bottom", fill="x", pady=(4, 0))
        cs.pack(side="right", fill="y")
        self.console.pack(fill="both", expand=True)
        self.cmd_var = tk.StringVar()
        e = ttk.Entry(ent, textvariable=self.cmd_var, font=("Consolas", 10))
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda ev: self._rcon_entry())
        ttk.Button(ent, text="Send", command=self._rcon_entry).pack(side="left", padx=(4, 0))

    def _tab_schedule(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Automation")
        split = ttk.PanedWindow(tab, orient="vertical")
        split.pack(fill="both", expand=True)
        sf = ScrollFrame(split)
        split.add(sf, weight=3)
        initial_sash(split, 0.6)
        top = sf.inner
        self._build_fields(top, SCHEDULE_FIELDS)
        bar = ttk.Frame(top)
        bar.pack(fill="x", padx=6, pady=2)
        ttk.Button(bar, text="Save automation settings", command=lambda: self._save_form(),
                   style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Stagger across servers...", command=self._stagger_dialog).pack(side="left", padx=4)
        self.next_restart_lbl = ttk.Label(bar, text="", style="Hint.TLabel")
        self.next_restart_lbl.pack(side="left", padx=10)

        lf = ttk.LabelFrame(split, text="Backups", padding=6)
        split.add(lf, weight=2)
        bb = FlowFrame(lf)
        bb.pack(fill="x", pady=(0, 4))
        for text, cmd in [("Backup now", self._backup_now), ("Restore selected...", self._restore),
                          ("Delete selected", self._delete_backup), ("Open backup folder", self._open_backup_dir),
                          ("Refresh", self._refresh_backups), ("Wipe / fresh start...", self._wipe_dialog)]:
            bb.add(ttk.Button(bb, text=text, command=cmd))
        self.btree = ttk.Treeview(lf, columns=("date", "size", "where"), show="tree headings", selectmode="browse",
                                  height=3)
        self.btree.heading("#0", text="File")
        self.btree.heading("date", text="Created")
        self.btree.heading("size", text="Size")
        self.btree.heading("where", text="Stored in")
        self.btree.column("#0", width=300, minwidth=120)
        self.btree.column("date", width=120, minwidth=80)
        self.btree.column("size", width=70, minwidth=50, anchor="e")
        self.btree.column("where", width=140, minwidth=70)
        bs = ttk.Scrollbar(lf, orient="vertical", command=self.btree.yview)
        self.btree.configure(yscrollcommand=bs.set)
        bs.pack(side="right", fill="y")
        self.btree.pack(fill="both", expand=True)

    def _tab_perf(self):
        tab = ttk.Frame(self.nb)
        self.perf_tab = tab
        self.nb.add(tab, text="Performance")
        top = ttk.LabelFrame(tab, text="All servers", padding=6)
        top.pack(fill="x", padx=6, pady=6)
        cols = ("status", "cpu", "ram", "limit", "uptime", "players")
        self.perf_tree = ttk.Treeview(top, columns=cols, show="tree headings", height=3, selectmode="browse")
        for c, label, w, anchor in [("#0", "Server", 170, "w"), ("status", "Status", 110, "w"),
                                    ("cpu", "CPU", 70, "e"), ("ram", "Memory", 90, "e"),
                                    ("limit", "Restart at", 90, "e"), ("uptime", "Uptime", 90, "e"),
                                    ("players", "Players", 70, "e")]:
            self.perf_tree.heading(c, text=label, anchor=anchor)
            self.perf_tree.column(c, width=w, anchor=anchor)
        self.perf_tree.pack(fill="x")
        self.perf_tree.bind("<<TreeviewSelect>>", self._perf_select)
        self.sys_lbl = ttk.Label(top, text="", style="Hint.TLabel")
        self.sys_lbl.pack(anchor="w", pady=(4, 0))

        charts = ttk.Frame(tab)
        charts.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        charts.columnconfigure(0, weight=1)
        charts.rowconfigure(0, weight=1)
        charts.rowconfigure(1, weight=1)
        self.ram_chart = tk.Canvas(charts, background=self.colors["chart_bg"], highlightthickness=1,
                                   highlightbackground=self.colors["chart_border"], height=110, width=300)
        self.cpu_chart = tk.Canvas(charts, background=self.colors["chart_bg"], highlightthickness=1,
                                   highlightbackground=self.colors["chart_border"], height=110, width=300)
        self.ram_chart.is_chart = self.cpu_chart.is_chart = True
        self.ram_chart.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        self.cpu_chart.grid(row=1, column=0, sticky="nsew")
        self._chart_pts = {}
        for c in (self.ram_chart, self.cpu_chart):
            c.bind("<Configure>", lambda e: self._refresh_perf())
            c.bind("<Motion>", self._chart_hover)
            c.bind("<Leave>", lambda e: e.widget.delete("hover"))
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_perf(), add="+")

    def _perf_select(self, _e=None):
        sel = self.perf_tree.selection()
        if sel and sel[0] != self.sel and self.tree.exists(sel[0]):
            self.tree.selection_set(sel[0])

    def _refresh_perf(self):
        if not hasattr(self, "perf_tree") or str(self.nb.select()) != str(self.perf_tab):
            return
        now = time.time()
        existing = set(self.perf_tree.get_children())
        for srv in self.cfg.servers:
            rt = self.mgr.runtime(srv["id"])
            running = rt.ram is not None
            vals = (rt.state,
                    f"{rt.cpu:.0f}%" if rt.cpu is not None and running else "–",
                    gb(rt.ram) if running else "–",
                    f"{float(srv.get('ram_restart_gb') or 0):g} GB" if float(srv.get("ram_restart_gb") or 0) else "off",
                    format_duration(now - rt.start_time) if running and rt.start_time else "–",
                    f"{len(rt.players)}/{srv['max_players']}" if rt.online else "–")
            if srv["id"] in existing:
                self.perf_tree.item(srv["id"], text=srv["name"], values=vals)
            else:
                self.perf_tree.insert("", "end", iid=srv["id"], text=srv["name"], values=vals)
        for iid in existing - {x["id"] for x in self.cfg.servers}:
            self.perf_tree.delete(iid)
        if self.sel and self.perf_tree.exists(self.sel) and self.perf_tree.selection() != (self.sel,):
            self.perf_tree.selection_set(self.sel)
        used, total = self.mgr.sys_mem
        self.sys_lbl.configure(text=f"This PC: {gb(used)} of {gb(total)} memory in use ({used / total:.0%})"
                               if total else "")
        s = self.current()
        if not s:
            return
        rt = self.mgr.runtime(s["id"])
        hist = list(rt.history)
        limit = float(s.get("ram_restart_gb") or 0)
        self._draw_chart(self.ram_chart, [(t, r / 1024 ** 3) for t, _c, r in hist if r is not None],
                         f"Memory - {s['name']}", lambda v: f"{v:.1f} GB",
                         floor_max=max(limit * 1.1, 4.0), threshold=limit or None,
                         threshold_label=f"Restart limit {limit:g} GB")
        self._draw_chart(self.cpu_chart, [(t, c) for t, c, _r in hist if c is not None],
                         f"CPU - {s['name']}", lambda v: f"{v:.0f}%", floor_max=20.0, cap=100.0)

    @staticmethod
    def _nice_scale(v):
        """Round axis: returns (max, step) with step = 1/2/5 x 10^n and 3-5 gridlines."""
        v = max(v, 1e-9)
        raw = v / 4
        mag = 10 ** math.floor(math.log10(raw))
        step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
        return step * math.ceil(v / step - 1e-9), step

    def _draw_chart(self, c, pts, title, fmt, floor_max=1.0, cap=None, threshold=None, threshold_label=""):
        """One-series time chart for the last hour: recessive grid, 2 px line, hover crosshair."""
        c_ = self.colors
        ink, muted, grid, line, warn = (c_["chart_ink"], c_["chart_muted"], c_["chart_grid"], c_["chart_line"],
                                        c_["chart_warn"])
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 120)
        L, R, T, B = 58, 16, 30, 24
        c.create_text(L, 14, text=title, anchor="w", fill=ink, font=("Segoe UI", 10, "bold"))
        now = time.time()
        x0 = now - 3600
        sx = lambda t: L + (t - x0) / 3600 * (w - L - R)
        vmax = max([v for _, v in pts] + [floor_max, (threshold or 0) * 1.05])
        ymax, step = self._nice_scale(vmax)
        if cap and ymax > cap:
            ymax, step = cap, 20.0
        sy = lambda v: T + (1 - v / ymax) * (h - T - B)
        for i in range(int(round(ymax / step)) + 1):
            v = step * i
            y = sy(v)
            c.create_line(L, y, w - R, y, fill=grid)
            c.create_text(L - 6, y, text=fmt(v).replace(".0 GB", " GB"), anchor="e", fill=muted, font=("Segoe UI", 8))
        for m in (60, 45, 30, 15, 0):
            x = sx(now - m * 60)
            c.create_text(x, h - B + 12, text="now" if m == 0 else f"-{m} min", fill=muted, font=("Segoe UI", 8))
        if threshold:
            y = sy(min(threshold, ymax))
            c.create_line(L, y, w - R, y, fill=warn, dash=(4, 3))
            c.create_text(w - R - 4, y - 8, text=threshold_label, anchor="e", fill=warn, font=("Segoe UI", 8))
        pts = [(t, v) for t, v in pts if t >= x0]
        self._chart_pts[str(c)] = (pts, sx, sy, fmt)
        if not pts:
            c.create_text((L + w - R) / 2, (T + h - B) / 2, text="No data yet - shown while the server is running",
                          fill=muted, font=("Segoe UI", 9))
            return
        c.create_text(w - R, 14, text=f"Now {fmt(pts[-1][1])} · peak {fmt(max(v for _, v in pts))}",
                      anchor="e", fill=ink, font=("Segoe UI", 9))
        seg = []
        for i, (t, v) in enumerate(pts):
            if seg and t - pts[i - 1][0] > 30:  # gap (server was down) -> break the line
                if len(seg) >= 4:
                    c.create_line(*seg, fill=line, width=2, capstyle="round", joinstyle="round")
                seg = []
            seg += [sx(t), sy(min(v, ymax))]
        if len(seg) >= 4:
            c.create_line(*seg, fill=line, width=2, capstyle="round", joinstyle="round")
        elif len(seg) == 2:
            c.create_oval(seg[0] - 3, seg[1] - 3, seg[0] + 3, seg[1] + 3, fill=line, outline="")

    def _chart_hover(self, e):
        c = e.widget
        c.delete("hover")
        data = self._chart_pts.get(str(c))
        if not data or not data[0]:
            return
        pts, sx, sy, fmt = data
        t, v = min(pts, key=lambda p: abs(sx(p[0]) - e.x))
        x, y = sx(t), sy(v)
        h = c.winfo_height()
        k = self.colors
        c.create_line(x, 30, x, h - 24, fill=k["chart_cross"], tags="hover")
        c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=k["chart_line"], outline=k["chart_bg"], width=2, tags="hover")
        label = f"{dt.datetime.fromtimestamp(t):%H:%M:%S}  {fmt(v)}"
        tx = x + 10 if x < c.winfo_width() - 150 else x - 10
        txt = c.create_text(tx, max(y - 14, 40), text=label, anchor="w" if tx > x else "e",
                            fill=k["chart_ink"], font=("Segoe UI", 9), tags="hover")
        bx = c.bbox(txt)
        rect = c.create_rectangle(bx[0] - 5, bx[1] - 3, bx[2] + 5, bx[3] + 3, fill=k["chart_bg"],
                                  outline=k["chart_border"], tags="hover")
        c.tag_lower(rect, txt)

    def _tab_log(self):
        tab = ttk.Frame(self.nb)
        self.log_tab = tab
        self.nb.add(tab, text="Log")
        self.logtxt = tk.Text(tab, wrap="word", font=("Consolas", 9), state="disabled", height=5, width=40)
        ls = ttk.Scrollbar(tab, orient="vertical", command=self.logtxt.yview)
        self.logtxt.configure(yscrollcommand=ls.set)
        ls.pack(side="right", fill="y")
        self.logtxt.pack(fill="both", expand=True)

    # ---- selection & form ------------------------------------------------------
    def current(self):
        return self.cfg.get(self.sel) if self.sel else None

    def _on_select(self, _e=None):
        items = self.tree.selection()
        new = items[0] if items else None
        if new == self.sel:
            return
        if self.sel and self.cfg.get(self.sel) and not self._save_form(silent=True):
            self.tree.selection_set(self.sel)
            return
        self.sel = new
        self._load_form()
        self._load_ini()
        self._reload_text(self.logtxt, self.mgr.runtime(new).log if new else [])
        self._reload_text(self.console, self.mgr.runtime(new).console if new else [])
        self._refresh_backups()
        self._refresh_installed_mods()
        self._refresh_mod_marks()
        self._refresh_tasks()
        self._refresh_plugins()
        self._refresh_header()

    def _load_form(self):
        s = self.current()
        if not s:
            return
        self._load_cmdline(s)
        for key, var in self.form_vars.items():
            v = s.get(key, "")
            var.set(bool(v) if isinstance(var, tk.BooleanVar) else str(v))
        self._update_cmd_preview()

    def _save_form(self, silent=False) -> bool:
        s = self.current()
        if not s:
            return True
        new = {}
        try:
            for key, var in self.form_vars.items():
                val = var.get()
                if isinstance(var, tk.BooleanVar):
                    new[key] = bool(val)
                    continue
                val = val.strip()
                if key in FLOAT_KEYS:
                    try:
                        val = float(val or 0)
                    except ValueError:
                        raise ValueError(f"'{key.replace('_', ' ')}' must be a number.")
                    if val < 0:
                        raise ValueError(f"'{key.replace('_', ' ')}' can't be negative.")
                    val = int(val) if val == int(val) else val
                elif key in INT_KEYS:
                    if not val.lstrip("-").isdigit():
                        raise ValueError(f"'{key.replace('_', ' ')}' must be a whole number.")
                    val = int(val)
                new[key] = val
            if not new["name"]:
                raise ValueError("Profile name can't be empty.")
            if not new["install_dir"]:
                raise ValueError("Install folder can't be empty.")
            if not new["map"]:
                raise ValueError("Pick a map.")
            for p in ("port", "rcon_port"):
                if not 1 <= new[p] <= 65535:
                    raise ValueError(f"{p} must be between 1 and 65535.")
            if new["port"] == new["rcon_port"]:
                raise ValueError("Game port and RCON port must differ.")
            for k in ("session_name", "admin_password", "server_password"):
                if any(ch in new[k] for ch in '?"'):
                    raise ValueError(f"{k.replace('_', ' ')} can't contain ? or \" characters.")
            for k in ("admin_password", "server_password"):
                if " " in new[k]:
                    raise ValueError(f"{k.replace('_', ' ')} can't contain spaces.")
            if not new["admin_password"]:
                raise ValueError("An admin password is required (it's also the RCON password).")
            mods = [m.strip() for m in new["mods"].split(",") if m.strip()]
            if any(not m.isdigit() for m in mods):
                raise ValueError("Mod IDs must be numbers separated by commas.")
            new["mods"] = ",".join(mods)
            parse_times(new["restart_times"])
            parse_minutes(new["restart_warn_minutes"])
            for o in self.cfg.servers:
                if o["id"] == s["id"]:
                    continue
                if {new["port"], new["rcon_port"]} & {o["port"], o["rcon_port"]}:
                    raise ValueError(f"Ports clash with server '{o['name']}' "
                                     f"(game {o['port']}, RCON {o['rcon_port']}).")
        except ValueError as e:
            if silent:
                if not messagebox.askyesno(APP_NAME, f"Unsaved changes for '{s['name']}' are invalid:\n\n{e}\n\n"
                                                     "Discard those changes?"):
                    return False
                self._load_form()
                return True
            messagebox.showerror(APP_NAME, str(e))
            return False
        try:
            cmd_vals = self._cmdline_values()
            self._validate_cmdline(cmd_vals)
            new.update(cmd_vals)
        except ValueError as e:
            if silent:
                if not messagebox.askyesno(APP_NAME, f"Unsaved launch options for '{s['name']}' are invalid:\n\n{e}"
                                                     "\n\nDiscard those changes?"):
                    return False
                self._load_form()
                return True
            messagebox.showerror(APP_NAME, str(e))
            return False
        cpu_changed = (s.get("cpu_priority"), s.get("cpu_cores")) != (new["cpu_priority"], new["cpu_cores"])
        changed = any(s.get(k) != v for k, v in new.items())
        if changed:
            s.update(new)
            self.cfg.save()
            self._refresh_server_list()
            self._refresh_header()
            self._update_cmd_preview()
            self._refresh_installed_mods()
            self._refresh_mod_marks()
            if not silent:
                self.mgr.log(s, "Settings saved.")
            if cpu_changed and self.mgr.is_running(s):
                threading.Thread(target=self.mgr.apply_cpu, args=(s,), kwargs={"force": True}, daemon=True).start()
        return True

    def _update_cmd_preview(self):
        self._preview_cmdline()
        s = self.current()
        self.cmd_preview.configure(state="normal")
        self.cmd_preview.delete("1.0", "end")
        if s:
            self.cmd_preview.insert("1.0", self.mgr.to_cmdline(self.mgr.build_command(s, mask=True)))
        self.cmd_preview.configure(state="disabled")

    def _toggle_pw(self):
        for e in self.pw_entries:
            e.configure(show="" if self.show_pw.get() else "•")

    def _browse_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or BASE_DIR)
        if d:
            var.set(os.path.normpath(d))

    # ---- INI editor ----------------------------------------------------------------
    def _ini_path(self, s, fname):
        return os.path.join(self.mgr.config_dir(s), fname)

    def _load_ini(self):
        s = self.current()
        for fname, txt in self.ini_texts.items():
            txt.delete("1.0", "end")
            if s:
                txt.insert("1.0", read_text_file(self._ini_path(s, fname)))
            txt.edit_reset()
        self._ini_texts_to_common()

    def _ini_texts_to_common(self):
        for (fname, section, key), var in self.common_vars.items():
            text = self.ini_texts[fname].get("1.0", "end-1c")
            v = ini_get(text, section, key)
            var.set(v if v is not None else "")

    def _common_to_ini_texts(self):
        for fname, txt in self.ini_texts.items():
            text = txt.get("1.0", "end-1c")
            new = text
            for (f, section, key), var in self.common_vars.items():
                if f != fname:
                    continue
                val = var.get().strip()
                cur = ini_get(new, section, key)
                if (cur or "") != val:
                    new = ini_set(new, section, key, val if val else None)
            if new != text:
                pos = txt.yview()
                txt.delete("1.0", "end")
                txt.insert("1.0", new)
                txt.yview_moveto(pos[0])

    def _ini_tab_changed(self, _e=None):
        idx = self.ini_nb.index("current")
        if self._ini_tab_prev == 0 and idx != 0:
            self._common_to_ini_texts()
        elif idx == 0 and self._ini_tab_prev != 0:
            self._ini_texts_to_common()
        self._ini_tab_prev = idx

    def _save_ini(self):
        s = self.current()
        if not s:
            return
        if self.ini_nb.index("current") == 0:
            self._common_to_ini_texts()
        else:
            self._ini_texts_to_common()
        if self.mgr.is_running(s) and not messagebox.askyesno(
                APP_NAME, "The server is running. ARK rewrites GameUserSettings.ini when it shuts down, "
                          "which can undo your edits.\n\nStop the server first, then save. Save anyway?"):
            return
        for fname, txt in self.ini_texts.items():
            path = self._ini_path(s, fname)
            if os.path.isfile(path):
                shutil.copy2(path, path + ".bak")
            write_text_file(path, txt.get("1.0", "end-1c"))
        self.mgr.log(s, "INI files saved (previous versions kept as .bak).")
        messagebox.showinfo(APP_NAME, "Saved. Changes take effect after the next restart.")

    # ---- server list -------------------------------------------------------------
    def _refresh_server_list(self):
        existing = set(self.tree.get_children())
        ids = []
        for s in self.cfg.servers:
            rt = self.mgr.runtime(s["id"])
            ids.append(s["id"])
            state = rt.state
            tag = "busy" if rt.busy else state
            players = str(len(rt.players)) if rt.online else "–"
            vals = (MAP_LABELS.get(s["map"], s["map"]), state, players)
            dot = self.status_dots.get(tag, self.status_dots["Stopped"])
            if s["id"] in existing:
                self.tree.item(s["id"], text=s["name"], values=vals, tags=(tag,), image=dot)
            else:
                self.tree.insert("", "end", iid=s["id"], text=s["name"], values=vals, tags=(tag,), image=dot)
        for iid in existing - set(ids):
            self.tree.delete(iid)
        for i, iid in enumerate(ids):
            self.tree.move(iid, "", i)
        n = sum(1 for s in self.cfg.servers if s.get("cluster"))
        self.cluster_lbl.configure(text=f"Cluster ID: {self.cfg.data['cluster_id']}\n"
                                        f"{n} server(s) in cluster. Change in File > Settings.")

    def _refresh_header(self):
        s = self.current()
        if not s:
            self.h_name.configure(text="No server selected")
            self.h_status.configure(text="")
            self.h_info.configure(text="")
            return
        rt = self.mgr.runtime(s["id"])
        self.h_name.configure(text=s["name"])
        status = rt.state
        if rt.online:
            status += f" · {len(rt.players)}/{s['max_players']} players"
        if rt.ram is not None:
            status += f" · RAM {gb(rt.ram)}" + (f" · CPU {rt.cpu:.0f}%" if rt.cpu is not None else "")
        if rt.countdown_until:
            status += f" · countdown to {rt.countdown_until:%H:%M}"
        color = self.colors["busy"] if rt.busy else self.colors["status"].get(rt.state, self.colors["fg"])
        self.h_status.configure(text=status, foreground=color)
        info = f"Build {rt.installed_build or '—'}"
        if self.mgr.latest_build:
            info += f" · latest {self.mgr.latest_build}"
            if self.mgr.update_available(s):
                info += " · UPDATE AVAILABLE"
        if rt.mods_outdated:
            info += f" · {len(rt.mods_outdated)} MOD UPDATE(S) - " + (
                "waiting for an empty server" if rt.mod_wait_since is not None else "restart to apply")
        self.h_info.configure(text=info)
        running = self.mgr.is_running(s)
        busy = bool(rt.busy)
        self.btns["start"].configure(state="disabled" if running or busy else "normal")
        self.btns["stop"].configure(state="normal" if running and not busy else "disabled")
        self.btns["restart"].configure(state="normal" if running and not busy else "disabled")
        self.btns["restart_warn"].configure(state="normal" if running and not busy else "disabled")
        self.btns["cancel"].configure(state="normal" if rt.countdown_until else "disabled")
        self.btns["update"].configure(state="disabled" if running or busy else "normal",
                                      text="Install" if not self.mgr.is_installed(s) else "Update")
        self.btns["validate"].configure(state="disabled" if running or busy else "normal")
        self.btns["kill"].configure(state="normal" if running else "disabled")
        self.toolbar.relayout()
        self.ini_warn.configure(text="Server is running - stop it before saving INI changes." if running else "")
        # players
        cur = [self.ptree.item(i, "values") for i in self.ptree.get_children()]
        want = [(p[1], p[2]) for p in rt.players]
        if [tuple(c) for c in cur] != want:
            self.ptree.delete(*self.ptree.get_children())
            for name, pid in want:
                self.ptree.insert("", "end", values=(name, pid))
        # next restart
        txt = ""
        try:
            times = parse_times(s.get("restart_times", ""))
            if times:
                txt = f"Next scheduled restart: {next_occurrence(times, dt.datetime.now()):%a %H:%M}"
        except ValueError:
            pass
        self.next_restart_lbl.configure(text=txt)
        if str(self.nb.select()) == str(self.perf_tab):
            self._refresh_perf()

    # ---- queue pump --------------------------------------------------------------
    def _pump(self):
        try:
            while True:
                kind, sid, payload = self.q.get_nowait()
                if kind == "log" and sid == self.sel:
                    self._append(self.logtxt, payload)
                elif kind == "console" and sid == self.sel:
                    self._append(self.console, payload)
                elif kind == "state":
                    self._dirty_state = True
                elif kind == "backups" and sid == self.sel:
                    self._refresh_backups()
                elif kind == "info":
                    messagebox.showinfo(APP_NAME, payload)
                elif kind == "error":
                    messagebox.showerror(APP_NAME, payload)
                elif kind == "call":
                    payload()
                elif kind == "tasks" and sid == self.sel:
                    self._refresh_tasks()
        except queue.Empty:
            pass
        if self._dirty_state:
            self._dirty_state = False
            self._refresh_server_list()
            self._refresh_header()
        self.root.after(250, self._pump)

    @staticmethod
    def _append(widget, text):
        at_end = widget.yview()[1] > 0.98
        widget.configure(state="normal")
        widget.insert("end", text + "\n")
        lines = int(widget.index("end-1c").split(".")[0])
        if lines > 3000:
            widget.delete("1.0", f"{lines - 3000}.0")
        widget.configure(state="disabled")
        if at_end:
            widget.see("end")

    @staticmethod
    def _reload_text(widget, lines):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines) + ("\n" if lines else ""))
        widget.configure(state="disabled")
        widget.see("end")

    # ---- actions -----------------------------------------------------------------
    def _need(self):
        s = self.current()
        if s and not self._save_form(silent=True):
            return None
        return s

    def _start(self):
        s = self._need()
        if s:
            self.mgr.run_op(s, "Starting", self.mgr.op_start)

    def _stop(self):
        s = self._need()
        if not s:
            return
        rt = self.mgr.runtime(s["id"])
        warns = []
        if rt.online and rt.players:
            ans = messagebox.askyesnocancel(APP_NAME, f"{len(rt.players)} player(s) online.\n\n"
                                                      "Yes = warn players with a countdown first\n"
                                                      "No = save and stop now")
            if ans is None:
                return
            if ans:
                try:
                    warns = parse_minutes(s.get("restart_warn_minutes", "")) or [5, 1]
                except ValueError:
                    warns = [5, 1]
        self.mgr.run_op(s, "Stopping", self.mgr.op_stop, warns)

    def _restart(self, warn=False):
        s = self._need()
        if not s:
            return
        warns = []
        if warn:
            try:
                warns = parse_minutes(s.get("restart_warn_minutes", "")) or [5, 1]
            except ValueError:
                warns = [5, 1]
        self.mgr.run_op(s, "Restarting", self.mgr.op_restart, False, warns, None, "Manual restart")

    def _cancel(self):
        s = self.current()
        if s:
            self.mgr.runtime(s["id"]).cancel_event.set()

    def _update(self, validate=False):
        s = self._need()
        if not s:
            return
        if not IS_WINDOWS and not os.path.isfile(self.mgr.steamcmd_exe()):
            messagebox.showwarning(APP_NAME, "This manager targets Windows; SteamCMD auto-download only works there.")
        self.nb.select(self.log_tab)
        self.mgr.run_op(s, "Validating" if validate else "Updating", self.mgr.op_update, validate)

    def _backup_now(self):
        s = self._need()
        if s:
            self.mgr.run_op(s, "Backing up", self.mgr.op_backup, "manual")

    def _kill(self):
        s = self.current()
        if s and messagebox.askyesno(APP_NAME, "Force-kill the server process without saving?\n"
                                               "Any progress since the last save will be lost."):
            rt = self.mgr.runtime(s["id"])
            rt.want_running = False
            rt.cancel_event.set()
            pid = rt.pid
            self.mgr.log(s, f"Force killing PID {pid}.")
            threading.Thread(target=kill_pid, args=(pid,), daemon=True).start()

    def _start_all(self):
        if not self._save_form(silent=True):
            return
        todo = [s for s in self.cfg.servers if not self.mgr.is_running(s)]
        if self.cfg.data.get("stagger_starts", True) and len(todo) > 1:
            self.mgr.start_staggered(todo)
            self.mgr.log(todo[0], f"Start all: {len(todo)} server(s) will start one at a time.")
            return
        for s in todo:
            self.mgr.run_op(s, "Starting", self.mgr.op_start)

    def _update_all_dialog(self):
        if not self._save_form(silent=True):
            return
        if getattr(self, "_update_all_win", None) is not None and self._update_all_win.winfo_exists():
            self._update_all_win.deiconify()
            self._update_all_win.lift()
            return
        d = tk.Toplevel(self.root)
        self._update_all_win = d
        d.title("Update all servers")
        d.transient(self.root)
        d.geometry("720x480")
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Updates your servers one at a time. Each one is stopped, updated and started again before "
                           "the next one begins, so only one server is ever down. Servers that share an install "
                           "folder are updated together.", wraplength=680, justify="left").pack(anchor="w")
        opts = ttk.Frame(fr)
        opts.pack(fill="x", pady=(8, 6))
        v = {k: tk.BooleanVar(value=val) for k, val in
             (("warn", True), ("restart", True), ("wait", True), ("skip", True), ("validate", False))}
        for key, text in (("warn", "Warn players first (uses each server's warning times)"),
                          ("restart", "Start servers again afterwards if they were running"),
                          ("wait", "Wait for each server to come back online before updating the next"),
                          ("skip", "Skip servers that are already on the latest build"),
                          ("validate", "Also validate files (slower; fixes damaged installs)")):
            ttk.Checkbutton(opts, text=text, variable=v[key]).pack(anchor="w")
        bar = ttk.Frame(fr)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        tree = ttk.Treeview(fr, columns=("status",), show="tree headings", height=4, selectmode="none")
        tree.heading("#0", text="Server (in order)")
        tree.heading("status", text="Status")
        tree.column("#0", width=200, minwidth=100)
        tree.column("status", width=440, minwidth=150)
        for s in self.cfg.servers:
            tree.insert("", "end", iid=s["id"], text=s["name"],
                        values=("Running - will update" if self.mgr.is_running(s) else "Stopped - will update",))
        cancel = threading.Event()
        b_start = ttk.Button(bar, text="Start updating")
        b_cancel = ttk.Button(bar, text="Cancel remaining", state="disabled")
        ttk.Button(bar, text="Close", command=d.withdraw).pack(side="right")
        ttk.Label(fr, text="You can close this window - updating carries on and is written to each server's Log.",
                  style="Hint.TLabel").pack(side="bottom", anchor="w", pady=(6, 0))

        def progress(s, status):
            def show():
                if d.winfo_exists() and tree.exists(s["id"]):
                    tree.set(s["id"], "status", status)
            self.q.put(("call", None, show))

        def start():
            if not messagebox.askyesno(APP_NAME, "Update all servers now? Running servers will be restarted "
                                                 "one at a time.", parent=d):
                return
            b_start.configure(state="disabled")
            b_cancel.configure(state="normal")
            servers = list(self.cfg.servers)
            for s in servers:
                progress(s, "Waiting for its turn")

            def work():
                try:
                    self.mgr.update_all(servers, warn=v["warn"].get(), restart=v["restart"].get(),
                                        wait_online=v["wait"].get(), skip_current=v["skip"].get(),
                                        validate=v["validate"].get(), progress=progress, cancel=cancel)
                except Exception as e:
                    self.q.put(("error", None, f"Update all stopped with an error:\n{e}"))

                def done():
                    if d.winfo_exists():
                        b_cancel.configure(state="disabled")
                        b_start.configure(state="normal", text="Run again")
                        cancel.clear()
                self.q.put(("call", None, done))
            threading.Thread(target=work, daemon=True, name="update-all").start()

        def stop():
            cancel.set()
            for s in self.cfg.servers:  # also aborts a countdown that is in progress
                rt = self.mgr.runtime(s["id"])
                if rt.busy == "Updating (all)":
                    rt.cancel_event.set()
            b_cancel.configure(state="disabled")

        tree.pack(fill="both", expand=True)
        b_start.configure(command=start)
        b_cancel.configure(command=stop)
        b_start.pack(side="left")
        b_cancel.pack(side="left", padx=4)
        self.themed_window(d)

    # ---- cluster broadcast / staggered restarts / wipe ------------------------------
    def _broadcast_all(self):
        online = [s["name"] for s in self.cfg.servers if self.mgr.runtime(s["id"]).online]
        if not online:
            messagebox.showinfo(APP_NAME, "No servers are online right now.")
            return
        msg = simpledialog.askstring(APP_NAME, f"Message to broadcast on all {len(online)} online server(s):\n"
                                               + ", ".join(online), parent=self.root)
        if not msg or not msg.strip():
            return

        def work():
            sent, skipped = self.mgr.broadcast_all(msg.strip())
            text = f"Broadcast sent to {len(sent)} server(s)."
            if skipped:
                text += f"\nNot sent (offline or RCON error): {', '.join(skipped)}"
            self.q.put(("info", None, text))
        threading.Thread(target=work, daemon=True).start()

    def _stagger_dialog(self):
        s = self._need()
        if not s:
            return
        d = tk.Toplevel(self.root)
        d.title("Stagger restart times")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Give every server the same daily restart schedule, spaced a few minutes apart, so the "
                           "cluster never goes down all at once and the PC only loads one map at a time. Servers "
                           "are spaced in the order of the server list.", wraplength=560, justify="left").pack(anchor="w")
        g = ttk.Frame(fr)
        g.pack(fill="x", pady=8)
        times_v = tk.StringVar(value=s.get("restart_times") or "04:00")
        gap_v = tk.StringVar(value="10")
        scope_v = tk.StringVar(value="cluster" if s.get("cluster") else "all")
        copy_v = tk.BooleanVar(value=True)
        ttk.Label(g, text="First server restarts at").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(g, textvariable=times_v, width=22).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(g, text="24h, comma separated", style="Hint.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Label(g, text="Minutes between servers").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(g, textvariable=gap_v, width=6).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(g, text="10-15 is usually enough for a map to load", style="Hint.TLabel").grid(row=1, column=2, sticky="w")
        sc = ttk.Frame(g)
        sc.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Radiobutton(sc, text="All servers", variable=scope_v, value="all").pack(side="left")
        ttk.Radiobutton(sc, text="Cluster servers only", variable=scope_v, value="cluster").pack(side="left", padx=10)
        ttk.Checkbutton(g, text=f"Also copy '{s['name']}' warning times and update-on-restart setting",
                        variable=copy_v).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        tree = ttk.Treeview(fr, columns=("times",), show="tree headings", height=5, selectmode="none")
        tree.heading("#0", text="Server")
        tree.heading("times", text="Restart times")
        tree.column("#0", width=200)
        tree.column("times", width=320)
        bar = ttk.Frame(fr)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        tree.pack(fill="both", expand=True)
        plan = {}

        def preview(*_):
            tree.delete(*tree.get_children())
            plan.clear()
            try:
                gap = int(gap_v.get())
                if not parse_times(times_v.get()) or gap < 0:
                    raise ValueError
            except ValueError:
                tree.insert("", "end", text="(enter valid times and minutes)", values=("",))
                return
            targets = [x for x in self.cfg.servers if scope_v.get() == "all" or x.get("cluster")]
            for i, srv in enumerate(targets):
                text = staggered_times(times_v.get(), i * gap)
                plan[srv["id"]] = text
                tree.insert("", "end", text=srv["name"], values=(text,))

        for var in (times_v, gap_v, scope_v):
            var.trace_add("write", preview)
        preview()

        def apply():
            if not plan:
                messagebox.showerror(APP_NAME, "Nothing to apply - check the times and minutes.", parent=d)
                return
            for sid, text in plan.items():
                srv = self.cfg.get(sid)
                srv["restart_times"] = text
                if copy_v.get() and srv is not s:
                    srv["restart_warn_minutes"] = s.get("restart_warn_minutes", "")
                    srv["update_on_scheduled_restart"] = s.get("update_on_scheduled_restart", True)
                self.mgr.log(srv, f"Restart times set to {text} (staggered).")
            self.cfg.save()
            self._load_form()
            self._refresh_header()
            d.destroy()
            messagebox.showinfo(APP_NAME, f"Restart times updated on {len(plan)} server(s).")

        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bar, text="Apply", command=apply).pack(side="right", padx=4)
        self.themed_window(d)

    def _wipe_dialog(self):
        s = self._need()
        if not s:
            return
        d = tk.Toplevel(self.root)
        d.title(f"Wipe / fresh start - {s['name']}")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Reset {s['name']} ({MAP_LABELS.get(s['map'], s['map'])}). Settings, mods and other "
                           "maps are never touched, and a backup is always taken first so you can undo it from "
                           "the Backups list.", wraplength=520, justify="left").pack(anchor="w")
        mode = tk.StringVar(value="wild")
        for value, title, desc in [
            ("wild", "Wild creatures only", "Kills every untamed creature so fresh ones spawn. Nothing else changes. "
                                            "The server must be online."),
            ("world", "World only - keep characters and tribes", "Removes all structures, tames and items on the "
                                                                 "map. Players keep their characters, levels and tribes."),
            ("all", "Everything on this map - brand new world", "World, characters and tribes are all removed. "
                                                                "Everyone starts from scratch."),
        ]:
            ttk.Radiobutton(fr, text=title, variable=mode, value=value).pack(anchor="w", pady=(8, 0))
            ttk.Label(fr, text=desc, style="Hint.TLabel", wraplength=500, justify="left").pack(anchor="w", padx=(24, 0))
        cluster_v = tk.BooleanVar(value=False)
        start_v = tk.BooleanVar(value=self.mgr.is_running(s))
        extra = ttk.Frame(fr)
        extra.pack(fill="x", pady=(10, 0))
        cb_cluster = ttk.Checkbutton(extra, text="Also clear cluster transfer data", variable=cluster_v)
        if s.get("cluster"):
            cb_cluster.pack(anchor="w")
            ttk.Label(extra, text="Uploaded characters, items and dinos - affects EVERY server in the cluster.",
                      style="Hint.TLabel").pack(anchor="w", padx=(24, 0), pady=(0, 4))
        ttk.Checkbutton(extra, text="Start the server again afterwards", variable=start_v).pack(anchor="w")

        def go():
            m = mode.get()
            if m == "wild":
                if not self.mgr.runtime(s["id"]).online:
                    messagebox.showinfo(APP_NAME, "The server needs to be online to wipe wild creatures.", parent=d)
                    return
                d.destroy()
                self.mgr.run_op(s, "Wiping wild dinos", self.mgr.op_wipe, "wild")
                return
            typed = simpledialog.askstring(APP_NAME, f"This permanently resets {s['name']}"
                                                     + (" AND the cluster's transfer data" if cluster_v.get() else "")
                                                     + ".\nA backup is taken first.\n\nType WIPE to continue:", parent=d)
            if (typed or "").strip().upper() != "WIPE":
                return
            d.destroy()
            self.nb.select(self.log_tab)
            self.mgr.run_op(s, "Wiping", self.mgr.op_wipe, m, cluster_v.get(), start_v.get())

        bar = ttk.Frame(fr)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bar, text="Wipe...", command=go).pack(side="right", padx=4)
        self.themed_window(d)

    def _find_event_mod(self):
        ev = self.form_vars.get("active_event").get().strip() if "active_event" in self.form_vars else ""
        self.nb.select(self.mods_tab)
        self.mod_query.set(EVENT_MOD_SEARCH.get(ev, ev or "event"))
        self._mod_search()

    def _stop_all(self):
        queued = self.mgr.start_queue_active
        if not messagebox.askyesno(APP_NAME, "Save and stop all running servers now?"
                                   + ("\n\nServers still waiting to start will not be started." if queued else "")):
            return
        self.mgr.cancel_start_queue()
        for s in self.cfg.servers:
            if self.mgr.is_running(s):
                self.mgr.run_op(s, "Stopping", self.mgr.op_stop, [])

    def _add_server(self, base=None):
        if not self._save_form(silent=True):
            return
        n = len(self.cfg.servers) + 1
        s = default_server(n, self.cfg.servers)
        s["install_dir"] = os.path.join(servers_root(self.cfg), safe_name(s["name"]))
        if base:
            keep = {k: v for k, v in base.items() if k not in ("id", "name", "install_dir", "port", "rcon_port",
                                                              "session_name", "autostart")}
            s.update(keep)
            s["name"] = base["name"] + " copy"
            s["session_name"] = base["session_name"] + " 2"
            s["install_dir"] = os.path.join(servers_root(self.cfg), safe_name(s["name"]))
        self.cfg.servers.append(s)
        self.cfg.save()
        self._refresh_server_list()
        self.tree.selection_set(s["id"])
        self.tree.see(s["id"])
        self.nb.select(0)

    def _clone_server(self):
        s = self.current()
        if s:
            base = json.loads(json.dumps(s))
            for t in base.get("timed_tasks", []):
                t["id"] = secrets.token_hex(4)
            self._add_server(base=base)

    def _copy_dialog(self):
        s = self._need()
        if not s:
            return
        others = [o for o in self.cfg.servers if o is not s]
        if not others:
            messagebox.showinfo(APP_NAME, "There are no other servers to copy to.")
            return
        if not self._save_form(silent=True):
            return
        d = tk.Toplevel(self.root)
        d.title(f"Copy from {s['name']}")
        d.transient(self.root)
        d.grab_set()
        self._copy_win = d
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Copy from {s['name']} to these servers:").pack(anchor="w")
        picked = {o["id"]: tk.BooleanVar(value=False) for o in others}
        for o in others:
            ttk.Checkbutton(fr, text=f"{o['name']} ({MAP_LABELS.get(o['map'], o['map'])})",
                            variable=picked[o["id"]]).pack(anchor="w", padx=8)
        ttk.Label(fr, text="What to copy:").pack(anchor="w", pady=(10, 0))
        mods_v, game_v, tamer_v = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        for var, text in [(mods_v, "Mods (replaces the list, load order and passive mods)"),
                          (game_v, "Game settings (GameUserSettings.ini and Game.ini)"),
                          (tamer_v, "Tamer settings (automation, backups, command line options)")]:
            ttk.Checkbutton(fr, text=text, variable=var).pack(anchor="w", padx=8)
        ttk.Label(fr, text="Name, map, ports, passwords and install folder are never copied. Neither are cluster, "
                           "plugins, public IP, CPU cores or auto-start. Running servers keep their game settings.",
                  style="Hint.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(10, 0))

        def apply():
            targets = [o for o in others if picked[o["id"]].get()]
            what = [t for t, v in (("mods", mods_v), ("game settings", game_v), ("Tamer settings", tamer_v)) if v.get()]
            if not targets or not what:
                messagebox.showerror(APP_NAME, "Tick at least one server and one thing to copy.", parent=d)
                return
            if not messagebox.askyesno(APP_NAME, f"Replace the {', '.join(what)} on "
                                                 f"{', '.join(o['name'] for o in targets)} with those from {s['name']}?",
                                       parent=d):
                return
            d.destroy()
            self._copy_run(s, targets, mods_v.get(), game_v.get(), tamer_v.get())

        bar = ttk.Frame(fr)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bar, text="Copy", command=apply).pack(side="right", padx=4)
        self.themed_window(d)

    def _copy_run(self, s, targets, mods, game, tamer):
        for o in targets:
            self.mgr.copy_settings_to(s, o, mods, tamer)
        self.cfg.save()
        self._refresh_server_list()

        def work():
            lines = []
            for o in targets:
                notes = []
                if mods or tamer:
                    what = " and ".join(t for t, on in (("Mods", mods), ("Tamer settings", tamer)) if on)
                    notes.append(f"{what} copied" + (", from the next restart." if self.mgr.is_running(o) else "."))
                if game:
                    try:
                        notes.append(self.mgr.copy_game_settings_to(s, o))
                    except OSError as e:
                        notes.append(f"Couldn't copy game settings: {e}. Check that the files aren't open elsewhere.")
                self.mgr.log(o, f"Copied from {s['name']}: {' '.join(notes)}")
                lines.append(f"{o['name']}: {' '.join(notes)}")
            summary = "\n\n".join(lines)
            self.q.put(("call", None, lambda: messagebox.showinfo(APP_NAME, summary)))

        threading.Thread(target=work, daemon=True).start()

    def _remove_server(self):
        s = self.current()
        if not s:
            return
        if self.mgr.is_running(s):
            messagebox.showwarning(APP_NAME, "Stop the server before removing it.")
            return
        if not messagebox.askyesno(APP_NAME, f"Remove '{s['name']}' from the manager?\n\n"
                                             f"Server files in {s['install_dir']} and backups are NOT deleted."):
            return
        self.cfg.servers.remove(s)
        self.cfg.save()
        self.sel = None
        self._refresh_server_list()
        if self.cfg.servers:
            self.tree.selection_set(self.cfg.servers[0]["id"])

    def _open_rel(self, rel):
        s = self.current()
        if not s:
            return
        path = os.path.join(s["install_dir"], rel) if rel else s["install_dir"]
        if not os.path.exists(path):
            messagebox.showinfo(APP_NAME, f"Doesn't exist yet:\n{path}\n\n(Install and start the server once.)")
            return
        open_path(path)

    def _open_backup_root(self):
        os.makedirs(self.cfg.data["backup_root"], exist_ok=True)
        open_path(self.cfg.data["backup_root"])

    def _open_cluster_dir(self):
        os.makedirs(self.cfg.data["cluster_dir"], exist_ok=True)
        open_path(self.cfg.data["cluster_dir"])

    # ---- troubleshooting & connectivity -----------------------------------------
    def _report_window(self, title, intro):
        d = tk.Toplevel(self.root)
        d.title(title)
        d.transient(self.root)
        d.geometry("760x560")
        d.configure(background=self.colors["bg"])
        fr = ttk.Frame(d, padding=10)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=intro, style="Hint.TLabel", wraplength=720, justify="left").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(fr)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        txt = tk.Text(fr, wrap="word", font=("Segoe UI", 10), padx=10, pady=8, relief="flat")
        sb = ttk.Scrollbar(fr, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        c = self.colors
        txt.tag_configure("title", font=("Segoe UI", 10, "bold"))
        txt.tag_configure("verdict", font=("Segoe UI", 11, "bold"), spacing3=8)
        for tag, color in (("error", c["bad"]), ("fail", c["bad"]), ("warning", c["warn"]), ("warn", c["warn"]),
                           ("ok", c["good"]), ("info", c["busy"]), ("unknown", c["muted"])):
            txt.tag_configure(tag, foreground=color, font=("Segoe UI", 10, "bold"))
        txt.tag_configure("detail", lmargin1=24, lmargin2=24, spacing3=2)
        txt.tag_configure("evidence", lmargin1=24, lmargin2=24, font=("Consolas", 9), foreground=c["muted"])
        txt.tag_configure("gap", spacing3=8)
        txt.insert("end", "Checking...")
        txt.configure(state="disabled")
        self.themed_window(d)
        return d, txt, bar

    def _troubleshoot(self):
        s = self._need()
        if not s:
            return
        d, txt, bar = self._report_window(f"Troubleshoot - {s['name']}",
                                          "Reads ShooterGame.log and checks this PC for the usual reasons an ASA "
                                          "server won't start, won't stay up, or doesn't show up.")
        report = {"text": ""}

        def run():
            def work():
                findings = diagnose_server(self.mgr, s)
                self.q.put(("call", None, lambda: show(findings)))
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", "Checking...")
            txt.configure(state="disabled")
            threading.Thread(target=work, daemon=True).start()

        def show(findings):
            if not d.winfo_exists():
                return
            report["text"] = format_findings(s, findings)
            labels = {"error": "PROBLEM", "warning": "WARNING", "info": "INFO", "ok": "OK"}
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            for f in findings:
                txt.insert("end", f"{labels[f['severity']]}  ", f["severity"])
                txt.insert("end", f["title"] + "\n", "title")
                if f["fix"]:
                    txt.insert("end", f["fix"] + "\n", "detail")
                for e in f["evidence"]:
                    txt.insert("end", e + "\n", "evidence")
                txt.insert("end", "\n", "gap")
            txt.configure(state="disabled")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(report["text"])

        ttk.Button(bar, text="Run again", command=run).pack(side="left")
        ttk.Button(bar, text="Copy report", command=copy).pack(side="left", padx=4)
        ttk.Button(bar, text="Open ShooterGame.log", command=lambda: self._open_rel(GAMELOG_REL)).pack(side="left")
        ttk.Button(bar, text="Validate files", command=lambda: (d.destroy(), self._update(validate=True))).pack(side="left", padx=4)
        ttk.Button(bar, text="Close", command=d.destroy).pack(side="right")
        run()

    def _connectivity(self):
        s = self._need()
        if not s:
            return
        d, txt, bar = self._report_window(f"Can players reach {s['name']}?",
                                          "Walks the path from this server to the internet: the server itself, "
                                          "Windows Firewall, your router (via UPnP) and the public server list. "
                                          "Takes about 10 seconds.")
        state = {"text": ""}
        b_upnp = ttk.Button(bar, text="Open port automatically (UPnP)", state="disabled")

        def run():
            b_upnp.configure(state="disabled")
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", "Checking...")
            txt.configure(state="disabled")

            def work():
                try:
                    res = check_connectivity(self.mgr, s)
                except Exception as e:
                    res = {"steps": [{"status": "fail", "title": "The check itself failed", "detail": str(e)}],
                           "verdict": "Couldn't complete the check.", "upnp": False}
                self.q.put(("call", None, lambda: show(res)))
            threading.Thread(target=work, daemon=True).start()

        def show(res):
            if not d.winfo_exists():
                return
            labels = {"ok": "OK", "fail": "PROBLEM", "warn": "WARNING", "unknown": "UNKNOWN"}
            lines = [f"Connectivity check for {s['name']} ({dt.datetime.now():%Y-%m-%d %H:%M})", res["verdict"], ""]
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", res["verdict"] + "\n", "verdict")
            for st in res["steps"]:
                txt.insert("end", f"{labels[st['status']]}  ", st["status"])
                txt.insert("end", st["title"] + "\n", "title")
                if st["detail"]:
                    txt.insert("end", st["detail"] + "\n", "detail")
                txt.insert("end", "\n", "gap")
                lines += [f"[{labels[st['status']]}] {st['title']}", f"    {st['detail']}" if st["detail"] else ""]
            txt.insert("end", "Tip: in-game, players find you under Unofficial servers with 'Show player servers' "
                              "ticked. Searching by your exact server name is quickest.\n", "detail")
            txt.configure(state="disabled")
            state["text"] = "\n".join(lines)
            if res.get("upnp"):
                b_upnp.configure(state="normal")

        def do_upnp():
            b_upnp.configure(state="disabled")

            def work():
                try:
                    res = upnp_open_port(s)
                except Exception as e:
                    res = str(e)
                def done():
                    if res == "OK":
                        s["upnp"] = True  # keep it open: re-applied every time the server starts
                        self.cfg.save()
                        self.mgr.log(s, f"UPnP: UDP {s['port']} forwarded to this PC (renewed on every start).")
                        messagebox.showinfo(APP_NAME, f"Your router now forwards UDP {s['port']} to this PC. "
                                                      "The manager will renew it whenever the server starts.", parent=d)
                        run()
                    else:
                        messagebox.showerror(APP_NAME, f"Couldn't open the port automatically:\n{res}", parent=d)
                        b_upnp.configure(state="normal")
                self.q.put(("call", None, done))
            threading.Thread(target=work, daemon=True).start()

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(state["text"])

        b_upnp.configure(command=do_upnp)
        ttk.Button(bar, text="Run again", command=run).pack(side="left")
        b_upnp.pack(side="left", padx=4)
        ttk.Button(bar, text="Open firewall port", command=self._firewall).pack(side="left")
        ttk.Button(bar, text="Search BattleMetrics", command=lambda: webbrowser.open(
            battlemetrics_search_url(s["session_name"]))).pack(side="left", padx=4)
        ttk.Button(bar, text="Copy report", command=copy).pack(side="left")
        ttk.Button(bar, text="Close", command=d.destroy).pack(side="right")
        run()

    def _firewall(self):
        s = self.current()
        if not s:
            return
        if not IS_WINDOWS:
            messagebox.showinfo(APP_NAME, "Firewall rules can only be added on Windows.")
            return
        name = f"ARK Ascended - {s['name']}".replace('"', "").replace("'", "")
        args = (f'advfirewall firewall add rule name="{name}" dir=in action=allow '
                f'protocol=UDP localport={s["port"]}')
        ps = f"Start-Process netsh -Verb RunAs -WindowStyle Hidden -ArgumentList '{args}'"
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=CREATE_NO_WINDOW, timeout=60)
            self.mgr.log(s, f"Requested Windows Firewall rule for UDP {s['port']} (approve the admin prompt).")
            messagebox.showinfo(APP_NAME, f"Approve the Windows admin prompt to open UDP port {s['port']}.\n\n"
                                          "Remember to also forward this UDP port on your router for players "
                                          "outside your network.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not add firewall rule:\n{e}")

    # ---- RCON UI ------------------------------------------------------------------
    def _rcon_send(self, cmd):
        s = self.current()
        if not s:
            return
        rt = self.mgr.runtime(s["id"])
        if not self.mgr.is_running(s):
            self.mgr.console(s, "(server is not running)")
            return
        self.mgr.console(s, f"> {cmd}")

        def work():
            try:
                out = self.mgr.rcon(s, cmd)
                if NO_RESPONSE in out:
                    out = "OK"
                if cmd.lower() == "listplayers":
                    rt.players = parse_players(out)
                    self.q.put(("state", s["id"], None))
                self.mgr.console(s, out or "OK")
            except Exception as e:
                self.mgr.console(s, f"RCON error: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _rcon_entry(self):
        cmd = self.cmd_var.get().strip()
        if cmd:
            self.cmd_var.set("")
            self._rcon_send(cmd)

    def _rcon_prompt(self, verb, prompt):
        msg = simpledialog.askstring(APP_NAME, prompt, parent=self.root)
        if msg:
            self._rcon_send(f"{verb} {msg}")

    def _destroy_wild(self):
        if messagebox.askyesno(APP_NAME, "Kill every wild (untamed) creature on the map so they respawn fresh?"):
            self._rcon_send("DestroyWildDinos")

    def _selected_player(self):
        sel = self.ptree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a player first.")
            return None
        return self.ptree.item(sel[0], "values")

    def _player_action(self, verb):
        p = self._selected_player()
        if p and messagebox.askyesno(APP_NAME, f"{verb.replace('Player', '')} {p[0]}?"):
            self._rcon_send(f"{verb} {p[1]}")

    def _copy_player_id(self):
        p = self._selected_player()
        if p:
            self.root.clipboard_clear()
            self.root.clipboard_append(p[1])

    def _clear_console(self):
        s = self.current()
        if s:
            self.mgr.runtime(s["id"]).console.clear()
            self._reload_text(self.console, [])

    # ---- backups UI -------------------------------------------------------------
    def _refresh_backups(self):
        self.btree.delete(*self.btree.get_children())
        s = self.current()
        if not s:
            return
        copy_dir = self.mgr.backup_copy_dir(s)
        copies = {os.path.basename(p) for p in self.mgr._zips(copy_dir)} if copy_dir else set()
        for path in self.mgr.list_backups(s):
            st = os.stat(path)
            name = os.path.basename(path)
            in_copy_only = copy_dir and os.path.dirname(path) == copy_dir
            where = "Second folder only" if in_copy_only else "Main + second folder" if name in copies else "Main"
            self.btree.insert("", "end", iid=path, text=name,
                              values=(dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                                      human_size(st.st_size), where))

    def _selected_backup(self):
        sel = self.btree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a backup first.")
            return None
        return sel[0]

    def _restore(self):
        s = self.current()
        path = self._selected_backup()
        if not s or not path:
            return
        if self.mgr.is_running(s):
            messagebox.showwarning(APP_NAME, "Stop the server before restoring.")
            return
        ans = messagebox.askyesnocancel(
            APP_NAME, f"Restore {os.path.basename(path)}?\n\nThe current saves are kept in a "
                      "'SavedArks_before_restore_…' folder.\n\nAlso restore the INI config files from this backup?")
        if ans is None:
            return
        self.mgr.run_op(s, "Restoring", self.mgr.op_restore, path, ans)

    def _delete_backup(self):
        path = self._selected_backup()
        s = self.current()
        if not path or not s:
            return
        name = os.path.basename(path)
        targets = [p for p in (os.path.join(self.mgr.backup_dir(s), name),
                               os.path.join(self.mgr.backup_copy_dir(s) or "", name)) if os.path.isfile(p)]
        extra = " (from both backup folders)" if len(targets) > 1 else ""
        if messagebox.askyesno(APP_NAME, f"Delete {name}{extra}?"):
            for p in targets:
                try:
                    os.remove(p)
                except OSError as e:
                    messagebox.showerror(APP_NAME, f"Couldn't delete {p}:\n{e}")
            self._refresh_backups()

    def _open_backup_dir(self):
        s = self.current()
        if s:
            d = self.mgr.backup_dir(s)
            os.makedirs(d, exist_ok=True)
            open_path(d)

    # ---- settings dialog ------------------------------------------------------
    def _test_webhook(self, url, parent):
        url = url.strip()
        if not url:
            messagebox.showinfo(APP_NAME, "Paste a Discord webhook URL first.", parent=parent)
            return

        def work():
            try:
                DiscordNotifier.post(url, self.mgr.discord.payload(
                    None, "Test message", f"{APP_NAME} notifications are working.", "good"))
                self.q.put(("info", None, "Test message sent - check your Discord channel."))
            except Exception as e:
                self.q.put(("error", None, f"Discord test failed:\n{e}"))

        threading.Thread(target=work, daemon=True).start()

    def _test_cf_key(self, var, parent):
        cleaned = clean_api_key(var.get())
        if cleaned != var.get():
            var.set(cleaned)  # show the user the cleaned-up key that will be saved

        def work():
            ok, msg = self.cf.test_key(cleaned)
            self.q.put(("call", None, lambda: (messagebox.showinfo if ok else messagebox.showerror)(
                APP_NAME, msg, parent=parent) if parent.winfo_exists() else None))

        threading.Thread(target=work, daemon=True).start()

    def _settings_dialog(self):
        d = tk.Toplevel(self.root)
        d.title("Settings")
        d.configure(background=self.colors["bg"])
        d.transient(self.root)
        d.grab_set()
        outer = ttk.Frame(d, padding=10)
        outer.pack(fill="both", expand=True)
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)
        data = self.cfg.data
        vars_ = {}

        def page(title):
            f = ttk.Frame(nb, padding=10)
            f.columnconfigure(1, weight=1)
            nb.add(f, text=title)
            return f

        def rows(frm, spec, start=0):
            for r, (key, label, kind) in enumerate(spec, start):
                ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
                v = tk.StringVar(value=str(data.get(key, "")))
                vars_[key] = v
                ttk.Entry(frm, textvariable=v, width=58).grid(row=r, column=1, sticky="ew", pady=3)
                if kind == "dir":
                    ttk.Button(frm, text="Browse...", command=lambda vv=v: self._browse_dir(vv)).grid(row=r, column=2, padx=4)
                elif kind == "cluster":
                    ttk.Button(frm, text="Generate", command=lambda vv=v: vv.set(secrets.token_hex(8))).grid(row=r, column=2, padx=4)
                elif kind == "apikey":
                    kb = ttk.Frame(frm)
                    kb.grid(row=r, column=2, padx=4, sticky="w")
                    ttk.Button(kb, text="Test key", command=lambda vv=v: self._test_cf_key(vv, d)).pack(side="left")
                    ttk.Button(kb, text="Get a free key", command=lambda: webbrowser.open(CF_CONSOLE_URL)).pack(
                        side="left", padx=(4, 0))
                elif kind == "webhook":
                    ttk.Button(frm, text="Send test", command=lambda vv=v: self._test_webhook(vv.get(), d)).grid(row=r, column=2, padx=4)
                elif kind == "bmtoken":
                    ttk.Button(frm, text="Get a free token", command=lambda: webbrowser.open(BATTLEMETRICS_TOKEN_URL)).grid(row=r, column=2, padx=4)
            return start + len(spec)

        def hint(frm, row, text):
            ttk.Label(frm, text=text, style="Hint.TLabel", wraplength=600, justify="left").grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # --- General
        g = page("General")
        r = rows(g, [("steamcmd_dir", "SteamCMD folder", "dir"), ("backup_root", "Backups folder", "dir"),
                     ("cluster_id", "Cluster ID", "cluster"), ("cluster_dir", "Cluster data folder", "dir"),
                     ("rcon_host", "RCON host", "text"),
                     ("update_check_min", "Check for game updates every (min, 0=off)", "text"),
                     ("curseforge_api_key", "CurseForge API key (optional)", "apikey"),
                     ("mod_check_min", "Check installed mods for updates every (min, 0=off)", "text"),
                     ("battlemetrics_token", "BattleMetrics token (optional)", "bmtoken")])
        ttk.Label(g, text="Second backup folder").grid(row=r, column=0, sticky="w", pady=3)
        copy_var = tk.StringVar(value=data.get("backup_copy_dir", ""))
        vars_["backup_copy_dir"] = copy_var
        ttk.Entry(g, textvariable=copy_var, width=58).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Button(g, text="Browse...", command=lambda: self._browse_dir(copy_var)).grid(row=r, column=2, padx=4)
        r += 1
        cloud = ttk.Frame(g)
        cloud.grid(row=r, column=1, columnspan=2, sticky="w")
        for label, path in cloud_folders():
            ttk.Button(cloud, text=f"Use {label}", command=lambda p=path: copy_var.set(
                os.path.join(p, "ARK Server Backups"))).pack(side="left", padx=(0, 4))
        ttk.Label(cloud, text="Every backup is also copied here - another drive or a cloud-synced folder.",
                  style="Hint.TLabel").pack(side="left", padx=4)
        r += 1
        stagger_v = tk.BooleanVar(value=data.get("stagger_starts", True))
        ttk.Checkbutton(g, text="Start servers one at a time (Start all and auto-start wait for each to come online)",
                        variable=stagger_v).grid(row=r, column=1, columnspan=2, sticky="w", pady=3)
        r += 1
        pre_upd = tk.BooleanVar(value=data.get("backup_before_update", True))
        ttk.Checkbutton(g, text="Back up saves before every game update", variable=pre_upd).grid(
            row=r, column=1, columnspan=2, sticky="w", pady=3)
        r += 1
        tamer_upd = tk.BooleanVar(value=data.get("tamer_update_check", True))
        ttk.Checkbutton(g, text="Check for new versions of Tamer (once a day, from GitHub)", variable=tamer_upd).grid(
            row=r, column=1, columnspan=2, sticky="w", pady=3)
        r += 1
        theme_labels = dict(THEME_CHOICES)
        theme_var = tk.StringVar(value=theme_labels.get(data.get("theme", "system"), "Match Windows"))
        ttk.Label(g, text="Appearance").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(g, textvariable=theme_var, values=[x[1] for x in THEME_CHOICES], state="readonly",
                     width=18).grid(row=r, column=1, sticky="w", pady=3)
        r += 1
        hint(g, r, "All servers in a cluster must share the same cluster ID and cluster folder; changes apply on the "
                   "next restart. Mod search works without a CurseForge key through a free community proxy - a "
                   "personal key (free at console.curseforge.com) is faster and more reliable.")

        # --- Discord
        dc = page("Discord")
        r = rows(dc, [("discord_webhook", "Webhook URL", "webhook"), ("discord_name", "Bot name", "text")])
        evf = ttk.LabelFrame(dc, text="Send notifications for", padding=6)
        evf.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ev_vars = {}
        for i, (key, label) in enumerate(DISCORD_EVENTS):
            ev_vars[key] = tk.BooleanVar(value=data.get("discord_events", {}).get(key, True))
            ttk.Checkbutton(evf, text=label, variable=ev_vars[key]).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 24), pady=1)
        hint(dc, r + 1, "Create a webhook in Discord: Server Settings > Integrations > Webhooks > New Webhook > "
                        "Copy Webhook URL. Each server can opt out on its Automation tab.")

        # --- Tray & background service
        bg = page("Tray & background service")
        close_tray = tk.BooleanVar(value=data.get("close_to_tray", True))
        min_tray = tk.BooleanVar(value=data.get("minimize_to_tray", False))
        tray_ok = bool(self.tray and self.tray.ok)
        ttk.Checkbutton(bg, text="Closing the window keeps the manager running in the system tray",
                        variable=close_tray, state="normal" if tray_ok else "disabled").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(bg, text="Minimizing the window sends it to the system tray",
                        variable=min_tray, state="normal" if tray_ok else "disabled").grid(row=1, column=0, columnspan=3, sticky="w")
        sw = tk.BooleanVar(value=IS_WINDOWS and startup_enabled())
        ttk.Checkbutton(bg, text="Open this manager window when I log in to Windows", variable=sw).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 6))
        if not tray_ok:
            hint(bg, 3, "The system tray icon is only available on Windows.")
        svc = ttk.LabelFrame(bg, text="Background service", padding=8)
        svc.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        svc.columnconfigure(0, weight=1)
        ttk.Label(svc, text="Runs the automation (crash restarts, schedules, backups, Discord, timed messages) as a "
                            "Windows startup task - even when nobody is logged in or this window is closed. It starts "
                            "with Windows, so servers with 'Start when the manager opens' come up after a reboot "
                            "on their own. While this window is open the service pauses and hands control "
                            "to the window, then takes it back when you close it.",
                  wraplength=600, justify="left").grid(row=0, column=0, columnspan=3, sticky="w")
        status = ttk.Label(svc, text="Checking...", style="Status.TLabel")
        status.grid(row=1, column=0, sticky="w", pady=(8, 0))
        b_install = ttk.Button(svc, text="Install service")
        b_remove = ttk.Button(svc, text="Remove service")
        b_install.grid(row=1, column=1, padx=4, pady=(8, 0))
        b_remove.grid(row=1, column=2, pady=(8, 0))
        ttk.Label(svc, text="Needs one admin (UAC) approval. Uses your Windows account (no password stored). "
                            "Standard (non-admin) accounts may lack the 'Log on as a batch job' right.",
                  style="Hint.TLabel", wraplength=600, justify="left").grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        def refresh_service():
            def work():
                inst = service_installed()
                live = service_info() is not None
                def show():
                    if not d.winfo_exists():
                        return
                    if not IS_WINDOWS:
                        status.configure(text="Only available on Windows", foreground=self.colors["muted"])
                        b_install.configure(state="disabled")
                        b_remove.configure(state="disabled")
                        return
                    k = self.colors
                    txt, col = (("Installed - running (paused while this window is open)", k["good"]) if inst and live
                                else ("Installed - not running", k["warn"]) if inst
                                else ("Not installed", k["muted"]))
                    status.configure(text=txt, foreground=col)
                    b_install.configure(state="disabled" if inst and live else "normal",
                                        text="Start service" if inst else "Install service")
                    b_remove.configure(state="normal" if inst else "disabled")
                self.q.put(("call", None, show))
            threading.Thread(target=work, daemon=True).start()

        def svc_action(action):
            status.configure(text="Waiting for the admin prompt..." if action != "start" else "Starting...",
                             foreground=self.colors["busy"])
            b_install.configure(state="disabled")
            b_remove.configure(state="disabled")

            def work():
                if action == "install":
                    res = install_service()
                elif action == "remove":
                    res = uninstall_service()
                else:
                    res = "OK" if start_service_task() else "Windows refused to start the task."
                time.sleep(2)
                if res != "OK":
                    self.q.put(("error", None, f"Background service: {res}"))
                elif action == "install":
                    self.q.put(("info", None, "Background service installed. It will keep managing your servers "
                                              "whenever this window is closed, and starts with Windows."))
                self.q.put(("call", None, refresh_service))

            threading.Thread(target=work, daemon=True).start()

        b_install.configure(command=lambda: svc_action("start" if b_install.cget("text") == "Start service" else "install"))
        b_remove.configure(command=lambda: messagebox.askyesno(
            APP_NAME, "Remove the background service? Servers keep running, but automation will only happen "
                      "while this window is open.", parent=d) and svc_action("remove"))
        refresh_service()

        def save():
            try:
                upd = int(vars_["update_check_min"].get().strip() or 0)
                modmin = int(vars_["mod_check_min"].get().strip() or 0)
            except ValueError:
                messagebox.showerror(APP_NAME, "Check intervals must be whole numbers.", parent=d)
                return
            cid = vars_["cluster_id"].get().strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", cid or ""):
                messagebox.showerror(APP_NAME, "Cluster ID must be letters/numbers only.", parent=d)
                return
            hook = vars_["discord_webhook"].get().strip()
            if hook and not re.match(r"https://(\w+\.)?discord(app)?\.com/api/webhooks/", hook):
                if not messagebox.askyesno(APP_NAME, "That doesn't look like a Discord webhook URL "
                                                     "(https://discord.com/api/webhooks/...). Save anyway?", parent=d):
                    return
            copy_dir = vars_["backup_copy_dir"].get().strip()
            if copy_dir and os.path.normcase(os.path.abspath(copy_dir)) == os.path.normcase(
                    os.path.abspath(vars_["backup_root"].get().strip())):
                messagebox.showerror(APP_NAME, "The second backup folder must be different from the main one.",
                                     parent=d)
                return
            for key in ("steamcmd_dir", "backup_root", "cluster_dir", "rcon_host", "curseforge_api_key",
                        "discord_webhook", "discord_name", "backup_copy_dir", "battlemetrics_token"):
                data[key] = vars_[key].get().strip()
            data["curseforge_api_key"] = clean_api_key(data["curseforge_api_key"])
            data["backup_before_update"] = pre_upd.get()
            data["tamer_update_check"] = tamer_upd.get()
            data["stagger_starts"] = stagger_v.get()
            data.update(cluster_id=cid, update_check_min=upd, mod_check_min=modmin,
                        discord_events={k: v.get() for k, v in ev_vars.items()},
                        close_to_tray=close_tray.get(), minimize_to_tray=min_tray.get(),
                        theme=next((k for k, v in THEME_CHOICES if v == theme_var.get()), "system"))
            self.cfg.save()
            self.apply_theme()
            if IS_WINDOWS:
                try:
                    set_start_with_windows(sw.get())
                except Exception as e:
                    messagebox.showerror(APP_NAME, f"Couldn't update the startup entry:\n{e}", parent=d)
            self._refresh_server_list()
            self._update_cmd_preview()
            d.destroy()

        bb = ttk.Frame(outer)
        bb.pack(fill="x", pady=(10, 0))
        ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bb, text="Save", command=save, style="Accent.TButton").pack(side="right", padx=4)
        self.themed_window(d)

    # ---- timed messages & commands ----------------------------------------------
    def _tab_tasks(self):
        tab = ttk.Frame(self.nb)
        self.tasks_tab = tab
        self.nb.add(tab, text="Messages")
        ttk.Label(tab, text="Messages and admin commands that run on a schedule while the server is online. "
                            f"Placeholders: {TASK_PLACEHOLDERS}", style="Hint.TLabel", wraplength=820,
                  justify="left").pack(anchor="w", padx=8, pady=(8, 2))
        bb = FlowFrame(tab)
        bb.pack(side="bottom", fill="x", padx=6, pady=(0, 8))
        lf = ttk.Frame(tab)
        lf.pack(fill="both", expand=True, padx=6, pady=4)
        cols = ("on", "kind", "schedule", "last")
        self.task_tree = ttk.Treeview(lf, columns=cols, show="tree headings", selectmode="browse", height=3)
        for c, label, wd, anchor in [("#0", "Message / command", 360, "w"), ("on", "State", 50, "center"),
                                     ("kind", "Type", 90, "w"), ("schedule", "Schedule", 170, "w"),
                                     ("last", "Last run", 80, "center")]:
            self.task_tree.heading(c, text=label, anchor=anchor)
            self.task_tree.column(c, width=wd, anchor=anchor, stretch=c == "#0")
        self.task_tree.tag_configure("off", foreground=self.colors["off"])
        ts = ttk.Scrollbar(lf, orient="vertical", command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=ts.set)
        ts.pack(side="right", fill="y")
        self.task_tree.pack(fill="both", expand=True)
        self.task_tree.bind("<Double-1>", lambda e: self._task_edit())
        for text, cmd in [("Add...", self._task_add), ("Edit...", self._task_edit), ("Turn on/off", self._task_toggle),
                          ("Remove", self._task_remove), ("Run now", self._task_run_now),
                          ("Copy to other servers", self._task_copy), ("Add examples", self._task_examples)]:
            bb.add(ttk.Button(bb, text=text, command=cmd))

    def _refresh_tasks(self):
        if not hasattr(self, "task_tree"):
            return
        sel = self.task_tree.selection()
        self.task_tree.delete(*self.task_tree.get_children())
        s = self.current()
        if not s:
            return
        rt = self.mgr.runtime(s["id"])
        for t in s.get("timed_tasks", []):
            last = rt.task_ran.get(t["id"])
            shown = f"{dt.datetime.fromtimestamp(last):%H:%M}" if last else "–"
            text = " / ".join(x.strip() for x in t.get("text", "").splitlines() if x.strip())
            self.task_tree.insert("", "end", iid=t["id"], text=text,
                                  values=("On" if t.get("enabled", True) else "Off", {"broadcast": "Broadcast", "chat": "Chat", "command": "Command"}.get(t.get("kind"), "?"),
                                          describe_task_schedule(t), shown),
                                  tags=() if t.get("enabled", True) else ("off",))
        if sel and self.task_tree.exists(sel[0]):
            self.task_tree.selection_set(sel[0])

    def _selected_task(self):
        s = self.current()
        sel = self.task_tree.selection()
        if not s or not sel:
            messagebox.showinfo(APP_NAME, "Select a timed message first.")
            return None, None
        return s, next((t for t in s.get("timed_tasks", []) if t["id"] == sel[0]), None)

    def _task_dialog(self, task=None):
        d = tk.Toplevel(self.root)
        d.title("Timed message / command")
        d.transient(self.root)
        d.grab_set()
        d.configure(background=self.colors["bg"])
        f = ttk.Frame(d, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        t = dict(task or {"kind": "broadcast", "mode": "interval", "every_min": 60, "times": "20:00",
                          "days": list(range(7)), "enabled": True, "text": ""})
        kind = tk.StringVar(value=TASK_KIND_LABELS[t.get("kind", "broadcast")])
        ttk.Label(f, text="Type").grid(row=0, column=0, sticky="w")
        ttk.Combobox(f, textvariable=kind, values=[x[1] for x in TASK_KINDS], state="readonly", width=34).grid(
            row=0, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Text").grid(row=1, column=0, sticky="nw", pady=3)
        txt = tk.Text(f, height=4, width=60, wrap="word", font=("Segoe UI", 10))
        txt.grid(row=1, column=1, sticky="ew", pady=3)
        txt.insert("1.0", t.get("text", ""))
        ttk.Label(f, text=f"Placeholders: {TASK_PLACEHOLDERS}\nFor admin commands, put one command per line "
                          "(e.g. SaveWorld, DestroyWildDinos).", style="Hint.TLabel", justify="left").grid(
            row=2, column=1, sticky="w")
        mode = tk.StringVar(value=t.get("mode", "interval"))
        every = tk.StringVar(value=str(t.get("every_min", 60)))
        times = tk.StringVar(value=t.get("times", ""))
        sch = ttk.LabelFrame(f, text="Schedule", padding=8)
        sch.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        r1 = ttk.Frame(sch)
        r1.pack(fill="x")
        ttk.Radiobutton(r1, text="Every", variable=mode, value="interval").pack(side="left")
        ttk.Entry(r1, textvariable=every, width=6).pack(side="left", padx=4)
        ttk.Label(r1, text="minutes (counted from when the server comes online)").pack(side="left")
        r2 = ttk.Frame(sch)
        r2.pack(fill="x", pady=(6, 0))
        ttk.Radiobutton(r2, text="At", variable=mode, value="times").pack(side="left")
        ttk.Entry(r2, textvariable=times, width=18).pack(side="left", padx=4)
        ttk.Label(r2, text="(24h, e.g. 12:00, 20:00) on:").pack(side="left")
        r3 = ttk.Frame(sch)
        r3.pack(fill="x", pady=(4, 0), padx=(22, 0))
        day_vars = []
        for i, name in enumerate(WEEKDAYS):
            v = tk.BooleanVar(value=i in (t.get("days") or range(7)))
            day_vars.append(v)
            ttk.Checkbutton(r3, text=name, variable=v).pack(side="left", padx=(0, 6))
        enabled = tk.BooleanVar(value=t.get("enabled", True))
        ttk.Checkbutton(f, text="Enabled", variable=enabled).grid(row=4, column=1, sticky="w", pady=(8, 0))
        result = {}

        def ok():
            text = txt.get("1.0", "end").strip()
            if not text:
                messagebox.showerror(APP_NAME, "Enter a message or command.", parent=d)
                return
            k = next(key for key, label in TASK_KINDS if label == kind.get())
            if mode.get() == "interval":
                if not every.get().strip().isdigit() or int(every.get()) < 1:
                    messagebox.showerror(APP_NAME, "Minutes must be a whole number of at least 1.", parent=d)
                    return
            else:
                try:
                    if not parse_times(times.get()):
                        raise ValueError("Enter at least one time, e.g. 20:00")
                except ValueError as e:
                    messagebox.showerror(APP_NAME, str(e), parent=d)
                    return
                if not any(v.get() for v in day_vars):
                    messagebox.showerror(APP_NAME, "Pick at least one day.", parent=d)
                    return
            if k == "command" and any(w in text.lower() for w in ("doexit", "destroyall")):
                if not messagebox.askyesno(APP_NAME, "That command shuts down the server or deletes things. "
                                                     "Schedule it anyway?", parent=d):
                    return
            result.update(id=t.get("id") or secrets.token_hex(4), kind=k, text=text, mode=mode.get(),
                          every_min=int(every.get()) if every.get().strip().isdigit() else 60,
                          times=", ".join(f"{h:02d}:{m:02d}" for h, m in parse_times(times.get() or "")) if mode.get() == "times" else times.get().strip(),
                          days=[i for i, v in enumerate(day_vars) if v.get()], enabled=enabled.get())
            d.destroy()

        bb = ttk.Frame(f)
        bb.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bb, text="OK", command=ok).pack(side="right", padx=4)
        self.themed_window(d)
        self.root.wait_window(d)
        return result or None

    def _save_tasks(self, s):
        self.cfg.save()
        self._refresh_tasks()

    def _task_add(self):
        s = self.current()
        if not s:
            return
        t = self._task_dialog()
        if t:
            s.setdefault("timed_tasks", []).append(t)
            self._save_tasks(s)
            self.mgr.log(s, f"Timed task added: {describe_task_schedule(t)} - {t['text'][:60]}")

    def _task_edit(self):
        s, t = self._selected_task()
        if not t:
            return
        new = self._task_dialog(t)
        if new:
            t.update(new)
            self.mgr.runtime(s["id"]).task_last.pop(t["id"], None)
            self._save_tasks(s)

    def _task_toggle(self):
        s, t = self._selected_task()
        if t:
            t["enabled"] = not t.get("enabled", True)
            self.mgr.runtime(s["id"]).task_last.pop(t["id"], None)
            self._save_tasks(s)

    def _task_remove(self):
        s, t = self._selected_task()
        if t and messagebox.askyesno(APP_NAME, "Remove this timed message?"):
            s["timed_tasks"].remove(t)
            self._save_tasks(s)

    def _task_run_now(self):
        s, t = self._selected_task()
        if not t:
            return
        if not self.mgr.runtime(s["id"]).online:
            messagebox.showinfo(APP_NAME, "The server isn't online, so there's nobody to send it to.")
            return
        threading.Thread(target=self.mgr.run_task, args=(s, t, True), daemon=True).start()

    def _task_copy(self):
        s, t = self._selected_task()
        if not t:
            return
        others = [o for o in self.cfg.servers if o is not s]
        if not others:
            messagebox.showinfo(APP_NAME, "There are no other servers to copy to.")
            return
        if not messagebox.askyesno(APP_NAME, f"Copy this timed message to {', '.join(o['name'] for o in others)}?"):
            return
        for o in others:
            o.setdefault("timed_tasks", []).append(dict(json.loads(json.dumps(t)), id=secrets.token_hex(4)))
        self.cfg.save()
        messagebox.showinfo(APP_NAME, f"Copied to {len(others)} server(s).")

    def _task_examples(self):
        s = self.current()
        if s:
            s.setdefault("timed_tasks", []).extend(example_tasks())
            self._save_tasks(s)
            messagebox.showinfo(APP_NAME, "Added 3 examples (turned off). Edit the text, then use 'Turn on/off'.")

    # ---- window / tray ----------------------------------------------------------
    def _show_window(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _on_unmap(self, e):
        if e.widget is self.root and self.root.state() == "iconic" and self.cfg.data.get("minimize_to_tray") \
                and self.tray and self.tray.ok:
            self.root.after(10, self.root.withdraw)

    def _on_close(self):
        if self.tray and self.tray.ok and self.cfg.data.get("close_to_tray", True):
            if not self._save_form(silent=True):
                return
            self._save_window_geometry()
            self.root.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.balloon(APP_NAME, "Still running in the system tray. Right-click the icon to exit.")
            return
        self._exit()

    def _exit(self):
        self._show_window()
        if not self._save_form(silent=True):
            return
        busy = [f"{s['name']}: {self.mgr.runtime(s['id']).busy}" for s in self.cfg.servers if self.mgr.runtime(s["id"]).busy]
        if busy and not messagebox.askyesno(APP_NAME, "These operations are still running and will be interrupted "
                                                      "if you exit now:\n  " + "\n  ".join(busy) + "\n\nExit anyway?"):
            return
        running = [s["name"] for s in self.cfg.servers if self.mgr.is_running(s)]
        has_service = service_info() is not None
        if running and not has_service and not messagebox.askyesno(
                APP_NAME, "These servers will keep running after you exit:\n  " + "\n  ".join(running) +
                          "\n\nCrash auto-restart, schedules, backups, timed messages and Discord alerts only work "
                          "while the manager is open - or install the background service (File > Settings > "
                          "Tray & background service). Exit anyway?"):
            return
        self._save_window_geometry()
        for srv in self.cfg.servers:  # countdowns end with this window; the service re-plans schedules itself
            self.mgr.runtime(srv["id"]).cancel_event.set()
        self.mgr.stop_event.set()
        if self.tray:
            self.tray.remove()
        release_gui_lock()
        self.root.destroy()


def acquire_gui_lock() -> bool:
    if gui_lock_owner():
        return False
    write_json_file(GUI_LOCK_PATH, {"pid": os.getpid(), "started": time.time()})
    return True


def release_gui_lock():
    info = read_json_file(GUI_LOCK_PATH)
    if info and info.get("pid") == os.getpid():
        try:
            os.remove(GUI_LOCK_PATH)
        except OSError:
            pass


def take_over_from_service(root) -> bool | None:
    """If the background service is running, pause it (waiting for its running jobs).
    Returns True if it took over, None if there was no service, False if the user gave up."""
    req = service_request({"cmd": "takeover"})
    if not req:
        return None
    ls, _info = req
    win = None
    state = {"result": None}
    try:
        while True:
            msg = ls.recv(0.2)
            if msg and msg.get("status") == "ready":
                state["result"] = True
                break
            if msg and msg.get("status") == "waiting" and win is None:
                win = tk.Toplevel(root)
                win.title(APP_NAME)
                win.resizable(False, False)
                fr = ttk.Frame(win, padding=14)
                fr.pack(fill="both")
                ttk.Label(fr, text="The background service is finishing a job before handing over:",
                          font=("Segoe UI", 10, "bold")).pack(anchor="w")
                lbl = ttk.Label(fr, text="", justify="left")
                lbl.pack(anchor="w", pady=8)
                bb = ttk.Frame(fr)
                bb.pack(fill="x")
                ttk.Button(bb, text="Cancel countdowns", command=lambda: ls.send({"cmd": "cancel"})).pack(side="left")
                ttk.Button(bb, text="Quit", command=lambda: state.update(result=False)).pack(side="right")
                win.protocol("WM_DELETE_WINDOW", lambda: state.update(result=False))
            if msg and msg.get("status") == "waiting" and win is not None:
                lbl.configure(text="\n".join(msg.get("busy", [])) + "\n\nThis window opens as soon as it's done.")
            if state["result"] is False:
                break
            root.update()
    except (OSError, ConnectionError, ValueError, tk.TclError):
        state["result"] = state["result"] or None
    finally:
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
        ls.close()
    return state["result"]


def main():
    if "--service" in sys.argv:
        run_service()
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    if IS_WINDOWS:
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:  # own taskbar button + icon instead of Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Tamer.ServerManager")  # type: ignore[attr-defined]
        except Exception:
            pass
    root = tk.Tk()
    root.withdraw()
    if not acquire_gui_lock():
        messagebox.showinfo(APP_NAME, "The manager is already open. Look for its icon in the system tray "
                                      "(near the clock).")
        root.destroy()
        return
    try:
        took = take_over_from_service(root)
        if took is False:
            root.destroy()
            return
        root.deiconify()
        App(root, took_over=bool(took))
        root.mainloop()
    finally:
        release_gui_lock()

if __name__ == "__main__":
    main()
