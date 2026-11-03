"""Mod update restarts that wait for an empty server: real fake server first, then the rules on their own."""
import json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

posts = []
file_ids = {"900001": 5001}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/api/webhooks/"):
            posts.append(body["embeds"][0]["title"]); self.send_response(204); self.end_headers(); return
        b = json.dumps({"data": [{"id": int(i), "name": f"Mod {i}", "mainFileId": file_ids[str(i)]} for i in body["modIds"]]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
tmp = tempfile.mkdtemp()
empty_flag = os.path.join(tmp, "everyone_left")
os.environ.update(ASM_CF_BASE=base + "/v1", FAKE_ARK_EMPTY=empty_flag, FAKE_ARK_LOG=os.path.join(tmp, "fk.log"))
sys.path.insert(0, sys.argv[1])
import tamer as am, fakes

cfg = am.AppConfig(os.path.join(tmp, "c.json"))
cfg.data.update(discord_webhook=base + "/api/webhooks/1/x", update_check_min=0, mod_check_min=0)
s = cfg.servers[0]
s.update(install_dir=os.path.join(tmp, "srv"), rcon_port=29901, port=28301, mods="900001", backup_interval_min=0,
         auto_mod_update_restart=True, mod_restart_wait_empty=True, restart_warn_minutes="5")
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe)); fakes.install_server(exe)
m = am.Manager(cfg, lambda *a: None); rt = m.runtime(s["id"])

def wait(cond, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return
        time.sleep(0.5)
    print("\n".join(rt.log)); raise SystemExit(f"TIMEOUT waiting for {what}")

# ---------- a player is online: it waits ----------
m.start_monitor(); m.run_op(s, "Start", m.op_start)
wait(lambda: rt.online and rt.players and rt.mod_files is not None, 40, "online with a player")
first = rt.pid
file_ids["900001"] = 5002
m.check_mod_updates()
assert rt.mod_wait_since and rt.mods_outdated == ["900001"], rt.mod_wait_since
wait(lambda: any("waiting for an empty server" in p for p in posts), 10, "waiting post")
time.sleep(12)
assert rt.pid == first and rt.mod_wait_since and not rt.busy, "must not restart with a player online"
print("waits while a player is online")

# ---------- everyone leaves: it restarts straight away, with no 5-minute warning ----------
open(empty_flag, "w").close()
t0 = time.time()
wait(lambda: rt.pid and rt.pid != first and rt.online, 60, "restart once empty")
print(f"restarted {time.time() - t0:.0f}s after everyone left")
assert rt.mod_wait_since is None and rt.mods_outdated == []
assert any("Mod update - restarting" in p for p in posts), posts
m.run_op(s, "Stop", m.op_stop, [])
wait(lambda: not m.is_running(s) and not rt.busy, 40, "stop")
m.stop_event.set()

# ---------- the rules on their own ----------
calls = []
def run_op(s_, label, fn, update, warns, target, reason):
    calls.append(warns); return True
m.run_op = run_op
def check(online, players, waited_min, **settings):
    calls.clear(); rt.restart_target = None; rt.busy = None
    s.update(auto_mod_update_restart=True, mod_restart_wait_empty=True, mod_restart_wait_minutes=120)
    s.update(settings)
    rt.online, rt.players = online, players
    rt.mod_wait_since, rt.mod_wait_names = time.time() - waited_min * 60, "Mod"
    return m._mod_wait_check(s, rt)

BOB = [("0", "Bob", "x")]
assert not check(True, BOB, 10) and not calls and rt.mod_wait_since, "a player is online: keep waiting"
assert not check(False, [], 10) and not calls, "a failed player check doesn't count as empty"
assert check(True, [], 10) and calls == [[]] and rt.mod_wait_since is None, "empty: restart with no warnings"
assert check(True, BOB, 121) and calls == [[5]], "time limit: restart with warnings"
assert not check(True, BOB, 100000, mod_restart_wait_minutes=0) and not calls, "0 means no limit"
assert check(True, BOB, 1, mod_restart_wait_empty=False) and calls == [[5]], "wait switched off: restart as normal"
assert not check(True, BOB, 1, auto_mod_update_restart=False) and rt.mod_wait_since is None, "auto restart off: stop waiting"
m.run_op = lambda *a: False
assert not check(True, [], 10) and rt.mod_wait_since and rt.restart_target is None, "a refused restart is tried again"
print("rules ok")
print("ALL OK")
