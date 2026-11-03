"""Integration test: start fake server -> online -> player join -> Discord -> RAM-limit restart -> mod update -> stop."""
import json, os, shutil, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

posts, first_429 = [], [True]
file_ids = {"900001": 5001, "900002": 6001}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/api/webhooks/"):
            if first_429[0]:
                first_429[0] = False
                return self._json(429, {"retry_after": 0.3})
            posts.append(body["embeds"][0]["title"]); self.send_response(204); self.end_headers(); return
        if self.path == "/v1/mods":
            return self._json(200, {"data": [{"id": int(i), "name": f"Mod {i}", "mainFileId": file_ids[str(i)]}
                                             for i in body["modIds"]]})
        self.send_response(404); self.end_headers()

srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ["ASM_CF_BASE"] = base + "/v1"
sys.path.insert(0, sys.argv[1])
import tamer as am

tmp = tempfile.mkdtemp()
cfg = am.AppConfig(os.path.join(tmp, "cfg.json"))
cfg.data.update(discord_webhook=base + "/api/webhooks/1/abc", update_check_min=0, mod_check_min=0)
cfg.data["discord_events"]["players"] = True
s = cfg.servers[0]
s.update(install_dir=os.path.join(tmp, "srv"), rcon_port=29123, mods="900001,900002",
         ram_restart_gb=0.1, restart_warn_minutes="", backup_interval_min=0)
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL)
os.makedirs(os.path.dirname(exe))
shutil.copy(os.path.join(os.path.dirname(__file__), "fake_ark_server.py"), exe)
os.chmod(exe, 0o755)
m = am.Manager(cfg, lambda *a: None)
rt = m.runtime(s["id"])

def wait(cond, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return
        time.sleep(0.5)
    print("\n".join(rt.log)); raise SystemExit(f"TIMEOUT waiting for {what}")

m.start_monitor()
m.run_op(s, "Starting", m.op_start)
wait(lambda: rt.online, 40, "online")
first_pid = rt.pid
print("online; pid", first_pid)
wait(lambda: rt.mod_files is not None, 15, "mod baseline")
assert rt.mod_files == {"900001": "5001", "900002": "6001"}, rt.mod_files
wait(lambda: any("Alice joined" in p for p in posts), 40, "Alice join post")
print("cpu", rt.cpu, "ram", am.gb(rt.ram), "history", len(rt.history))
assert rt.cpu is not None and rt.ram and len(rt.history) >= 2

# mod update detection (auto-restart off -> alert only)
file_ids["900002"] = 6002
m.check_mod_updates()
assert rt.mods_outdated == ["900002"], rt.mods_outdated
wait(lambda: any("Mod update available" in p for p in posts), 10, "mod post")

# RAM limit restart: fake server grows to ~180 MB; limit 0.1 GB -> restart after ~30s above
wait(lambda: rt.pid and rt.pid != first_pid and rt.online, 120, "memory restart")
print("restarted; new pid", rt.pid)
assert any("High memory - restarting" in p for p in posts)
assert rt.mods_outdated == [] and rt.mod_files is None or rt.mod_files == {"900001": "5001", "900002": "6002"}

# clean stop
s["ram_restart_gb"] = 0
m.run_op(s, "Stopping", m.op_stop, [])
wait(lambda: not m.is_running(s) and not rt.busy, 60, "stop")
time.sleep(2)
m.stop_event.set()
print("POSTS:")
for p in posts: print("  ", p)
need = ["Online", "Alice joined", "Mod update available", "High memory - restarting",
        "Restarting now", "Stopped"]
assert not any("Bob joined" in p for p in posts), "players present at startup must not be announced"
for n in need:
    assert any(n in p for p in posts), f"missing post: {n}"
assert not any("Crashed" in p for p in posts), "restart must not look like a crash"
print("\n".join(l for l in rt.log if "Player" in l or "Memory" in l or "Mod" in l))
print("ALL OK")
