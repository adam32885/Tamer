#!/usr/bin/env python3
"""Pretends to be ArkAscendedServer.exe: RCON server, players joining, growing memory."""
import os, re, socket, struct, sys, threading, time

url = sys.argv[1]
rport = int(re.search(r"RCONPort=(\d+)", url).group(1))
pw = re.search(r"ServerAdminPassword=([^?]+)", url).group(1)
log = open(os.environ.get("FAKE_ARK_LOG", __import__("os").path.join(__import__("tempfile").gettempdir(), "fake_ark.log")), "a")
log.write(f"started {os.getpid()} args={sys.argv[1:]}\n"); log.flush()
start = time.time()
hog = []
frozen = getattr(sys, "frozen", False)  # the Windows test exe (see fakes.py)
gamelog_path = os.path.join(os.path.dirname(os.path.abspath(sys.executable if frozen else sys.argv[0])),
                            "..", "..", "Saved", "Logs", "ShooterGame.log")
os.makedirs(os.path.dirname(gamelog_path), exist_ok=True)
gamelog = open(gamelog_path, "w")
gamelog.write("[2026.11.02-10.00.00:000][  0]Log file open\n"); gamelog.flush()
if os.environ.get("FAKE_ARK_CRASH"):
    gamelog.write("[2026.11.02-10.00.01:000][  0]LogCurseForge: Error: Failed to download mod 123456 (not found)\n")
    gamelog.write("[2026.11.02-10.00.02:000][  0]Fatal error: [File:Unknown] EXCEPTION_ACCESS_VIOLATION reading address 0x0\n")
    gamelog.close(); sys.exit(3)
stop = threading.Event()

def players():
    if os.path.exists(os.environ.get("FAKE_ARK_EMPTY", "")):  # this file existing means everyone has left
        return "No Players Connected\n"
    t = time.time() - start
    ps = ["0. Bob, 0002aaaa"]
    if t > 14:
        ps.append("1. Alice, 0002bbbb")
    return "\n".join(ps) + "\n"

def pkt(i, t, body):
    p = struct.pack("<ii", i, t) + body.encode() + b"\0\0"
    return struct.pack("<i", len(p)) + p

def handle(c):
    authed = False
    try:
        while True:
            hdr = c.recv(4)
            if not hdr:
                return
            n = struct.unpack("<i", hdr)[0]
            d = b""
            while len(d) < n:
                d += c.recv(n - len(d))
            i, t = struct.unpack("<ii", d[:8]); body = d[8:-2].decode()
            if t == 3:
                authed = body == pw
                c.sendall(pkt(i if authed else -1, 2, ""))
            elif authed:
                log.write(f"cmd {body}\n"); log.flush()
                if body == "ListPlayers":
                    c.sendall(pkt(i, 0, players()))
                elif body == "DoExit":
                    c.sendall(pkt(i, 0, "Exiting..."))
                    stop.set()
                else:
                    c.sendall(pkt(i, 0, "Server received, But no response!! "))
    except OSError:
        pass

def serve():
    time.sleep(3)  # "map loading"
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", rport)); s.listen()
    gamelog.write("[2026.11.02-10.00.05:000][  0]Server has completed startup and is now advertising for join.\n"); gamelog.flush()
    while True:
        c, _ = s.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

def windows():
    """Like the real server: an "ASA ..." log window, plus one other window Tamer must leave alone."""
    import ctypes, ctypes.wintypes as wt
    u = ctypes.windll.user32
    u.CreateWindowExW.restype = wt.HWND
    u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD] + [ctypes.c_int] * 4 + [wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    for title, x in ((f"ASA 96.9 | Process {os.getpid()} | Mem: 0.5 GB | Booting...", 0), ("Some other window", 420)):
        u.CreateWindowExW(0, "STATIC", title, 0x10CF0000, x, 0, 400, 200, None, None, None, None)  # visible overlapped
    msg = wt.MSG()
    while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))

threading.Thread(target=serve, daemon=True).start()
if os.environ.get("FAKE_ARK_WINDOWS") and os.name == "nt":
    threading.Thread(target=windows, daemon=True).start()
gport = int(re.search(r"Port=(\d+)", url.split("RCONPort")[0]).group(1))
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # the game port; local only on Windows, to avoid firewall popups
udp.bind(("127.0.0.1" if frozen else "0.0.0.0", gport))
while not stop.is_set():
    if time.time() - start > 8 and len(hog) < 3:
        hog.append(bytearray(os.urandom(1)) * (60 * 1024 * 1024))  # ~180 MB total -> trips a 0.1 GB limit
    x = sum(range(20000))  # a little CPU
    time.sleep(0.05)
log.write(f"exiting {os.getpid()}\n"); log.flush()
