import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good":
            self.send_response(403); self.end_headers(); return
        b = json.dumps({"data": [{"attributes": {"name": "My Srv", "ip": "93.184.216.34", "port": 7777, "players": 3, "maxPlayers": 70, "status": "online"}}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
h = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=h.serve_forever, daemon=True).start()
os.environ["ASM_BM_URL"] = f"http://127.0.0.1:{h.server_address[1]}/servers"
sys.path.insert(0, sys.argv[1]); import tamer as am
for tok, expect in (("", "token required"), ("bad", "token rejected")):
    try: am.battlemetrics_lookup("My Srv", tok); raise SystemExit("should refuse")
    except am.BattleMetricsRefused as e: assert str(e) == expect, e
r = am.battlemetrics_lookup("My Srv", "good"); assert r[0]["players"] == 3
# connectivity step wording without a token
import tempfile
cfg = am.AppConfig(os.path.join(tempfile.mkdtemp(), "c.json")); m = am.Manager(cfg, lambda *a: None)
s = cfg.servers[0]; m.runtime(s["id"]).online = True
am.public_ip = lambda: "93.184.216.34"; am.UPnP.discover = lambda self, timeout=3: False
steps = am.check_connectivity(m, s)["steps"]
st = [x for x in steps if "BattleMetrics" in x["title"]][0]; print(st["title"]); assert "needs a free token" in st["title"]
cfg.data["battlemetrics_token"] = "good"; s["session_name"] = "My Srv"
st = [x for x in am.check_connectivity(m, s)["steps"] if "listed" in x["title"]][0]; print(st["title"], "-", st["detail"])
assert st["status"] == "ok"
print(am.battlemetrics_search_url("My Srv")); print("ALL OK")
