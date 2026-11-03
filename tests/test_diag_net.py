"""Backups to a second folder, troubleshooter, connectivity check (mock router/UPnP, ipify, BattleMetrics)."""
import json, os, shutil, socket, sys, tempfile, threading, time, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

router = {"ext_ip": "93.184.216.34", "maps": {}}
posts = []
BM = {"data": []}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/ipify"): return self._send(200, json.dumps({"ip": "93.184.216.34"}))
        if self.path.startswith("/bm"):
            assert "filter%5Bgame%5D=arksa" in self.path, self.path
            return self._send(200, json.dumps(BM))
        if self.path == "/igd.xml":
            return self._send(200, """<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>
            <deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType><deviceList><device><deviceList><device>
            <serviceList><service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
            <controlURL>/ctl/IPConn</controlURL></service></serviceList></device></deviceList></device></deviceList></device></root>""", "text/xml")
        self._send(404, "{}")
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if self.path.startswith("/api/webhooks"):
            posts.append(json.loads(body)["embeds"][0]["title"]); return self._send(204, "")
        action = self.headers["SOAPAction"].strip('"').split("#")[1]
        import re
        val = lambda k: (re.search(f"<{k}>(.*?)</{k}>", body) or [None, ""])[1]
        ns = "urn:schemas-upnp-org:service:WANIPConnection:1"
        if action == "GetExternalIPAddress":
            res = f"<NewExternalIPAddress>{router['ext_ip']}</NewExternalIPAddress>"
        elif action == "GetSpecificPortMappingEntry":
            m = router["maps"].get((val("NewExternalPort"), val("NewProtocol")))
            if not m:
                fault = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault>'
                         '<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0"><errorCode>714</errorCode>'
                         '<errorDescription>NoSuchEntryInArray</errorDescription></UPnPError></detail></s:Fault></s:Body></s:Envelope>')
                return self._send(500, fault, "text/xml")
            res = f"<NewInternalPort>{val('NewExternalPort')}</NewInternalPort><NewInternalClient>{m}</NewInternalClient><NewEnabled>1</NewEnabled>"
        elif action == "AddPortMapping":
            router["maps"][(val("NewExternalPort"), val("NewProtocol"))] = val("NewInternalClient"); res = ""
        self._send(200, f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                        f'<u:{action}Response xmlns:u="{ns}">{res}</u:{action}Response></s:Body></s:Envelope>', "text/xml")

http = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=http.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{http.server_address[1]}"
ssdp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); ssdp.bind(("127.0.0.1", 0))
def ssdp_loop():
    while True:
        data, addr = ssdp.recvfrom(2048)
        if b"M-SEARCH" in data:
            ssdp.sendto(f"HTTP/1.1 200 OK\r\nLOCATION: {base}/igd.xml\r\nST: x\r\n\r\n".encode(), addr)
threading.Thread(target=ssdp_loop, daemon=True).start()
os.environ.update(ASM_SSDP_ADDR=f"127.0.0.1:{ssdp.getsockname()[1]}", ASM_IPIFY_URL=base + "/ipify", ASM_BM_URL=base + "/bm",
                  FAKE_ARK_LOG=__import__("os").path.join(__import__("tempfile").gettempdir(), "fk2.log"))
sys.path.insert(0, sys.argv[1])
import tamer as am

tmp = tempfile.mkdtemp()
cfg = am.AppConfig(os.path.join(tmp, "c.json"))
cfg.data.update(update_check_min=0, mod_check_min=0, backup_root=os.path.join(tmp, "bk"),
                backup_copy_dir=os.path.join(tmp, "cloud"), discord_webhook=base + "/api/webhooks/1/x")
s = cfg.servers[0]
s.update(install_dir=os.path.join(tmp, "srv"), rcon_port=29411, port=27777, backup_keep=2, session_name="Unique Test Server 42")
m = am.Manager(cfg, lambda *a: None); rt = m.runtime(s["id"])

# ---------- 1. backups to a second folder ----------
arks = os.path.join(s["install_dir"], am.SAVEDARKS_REL, "TheIsland_WP"); os.makedirs(arks)
open(os.path.join(arks, "TheIsland_WP.ark"), "w").write("W1")
for i in range(3):
    m._backup(s, f"b{i}"); time.sleep(1.05)
main, cop = m._zips(m.backup_dir(s)), m._zips(m.backup_copy_dir(s))
assert len(main) == 2 and len(cop) == 2 and [os.path.basename(x) for x in main] == [os.path.basename(x) for x in cop]
shutil.rmtree(m.backup_dir(s))                      # main drive "dies"
lst = m.list_backups(s); assert len(lst) == 2 and all(p.startswith(os.path.join(tmp, "cloud")) for p in lst)
open(os.path.join(arks, "TheIsland_WP.ark"), "w").write("BROKEN")
m._restore(s, lst[0], False)
assert open(os.path.join(arks, "TheIsland_WP.ark")).read() == "W1"
try:
    m._update(s)                                     # pre-update backup happens before SteamCMD (which fails on Linux)
except RuntimeError:
    pass
assert any("pre-update" in p for p in m.list_backups(s)), m.list_backups(s)
print("backups ok")

# ---------- 2. troubleshooter ----------
f = am.diagnose_server(m, s)
assert f[0]["title"] == "The server isn't installed"
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe))
shutil.copy("fake_ark_server.py", exe); os.chmod(exe, 0o755)
blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); blocker.bind(("0.0.0.0", 27777))
f = am.diagnose_server(m, s); titles = [x["title"] for x in f]
assert "The game port 27777 (UDP) is already in use" in titles, titles
blocker.close()
logdir = os.path.join(s["install_dir"], "ShooterGame", "Saved", "Logs"); os.makedirs(logdir, exist_ok=True)
open(os.path.join(logdir, "ShooterGame.log"), "w").write(
    "LogMemory: Fatal: Ran out of memory allocating 123 bytes\nLogWorld: Failed to load package /Game/Maps/Astraeos_WP\n"
    "LogEOS: Error: Failed to register session\n")
f = am.diagnose_server(m, s); titles = [x["title"] for x in f]
print(titles)
for t in ("The server ran out of memory", "The map couldn't be loaded", "Epic Online Services (the server list) reported errors"):
    assert t in titles, t
assert f[0]["severity"] == "error" and f[0]["evidence"]
print(am.format_findings(s, f)[:300])
print("diagnose ok")

# auto-diagnose when a server crashes before it finishes starting
os.environ["FAKE_ARK_CRASH"] = "1"
s["auto_restart_on_crash"] = False
m.start_monitor(); m.run_op(s, "Start", m.op_start)
end = time.time() + 30
while time.time() < end and not any("Crashed before it finished starting" in p for p in posts): time.sleep(0.5)
assert any("Crashed before it finished starting" in p for p in posts), posts
assert any("Troubleshooter: A mod had trouble" in l for l in rt.log) and any("Troubleshooter: The server crashed" in l for l in rt.log)
del os.environ["FAKE_ARK_CRASH"]
print("auto-diagnose ok")

# ---------- 3. connectivity ----------
s["auto_restart_on_crash"] = True
m.run_op(s, "Start", m.op_start)
end = time.time() + 30
while time.time() < end and not rt.online: time.sleep(0.5)
assert rt.online
lan = am.local_ip()
r = am.check_connectivity(m, s)
for st in r["steps"]: print(" ", st["status"], st["title"])
assert r["upnp"] and any(st["status"] == "fail" and "isn't forwarding" in st["title"] for st in r["steps"])
assert "blocking" in r["verdict"]
assert am.upnp_open_port(s) == "OK" and router["maps"][("27777", "UDP")] == lan
BM["data"] = [{"attributes": {"name": "Unique Test Server 42", "ip": "93.184.216.34", "port": 27777, "players": 1, "maxPlayers": 70, "status": "online"}}]
r = am.check_connectivity(m, s)
print(r["verdict"])
assert any(st["status"] == "ok" and "forwards UDP 27777" in st["title"] for st in r["steps"])
assert "should be able to find and join" in r["verdict"]
router["ext_ip"] = "100.72.5.9"   # carrier-grade NAT
r = am.check_connectivity(m, s)
assert any("doesn't have a public internet address" in st["title"] for st in r["steps"]) and "CGNAT" in r["verdict"], r
print("connectivity ok")
m.run_op(s, "Stop", m.op_stop, []); time.sleep(8); m.stop_event.set()
print("ALL OK")
