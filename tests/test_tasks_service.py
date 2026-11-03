"""Timed tasks + background service handoff, end to end (Linux stand-in for Windows).

1. timed tasks fire with placeholders (interval / time+day / multi-command) and don't double-fire
2. --service starts, autostarts the server, posts Online
3. the window takes over during a restart countdown -> waits -> cancels -> service pauses
4. window engine adopts the running server without re-announcing it
5. window closes -> service resumes and handles a crash
6. shutdown command stops the service; game server keeps running
"""
import datetime as dt, json, os, shutil, signal, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1]
PY = sys.executable
posts = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        posts.append(body["embeds"][0]["title"]); self.send_response(204); self.end_headers()

hs = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=hs.serve_forever, daemon=True).start()
hook = f"http://127.0.0.1:{hs.server_address[1]}/api/webhooks/1/x"

base = tempfile.mkdtemp()
for f_ in ("ark_manager.py", "tamer.py", "tamer.ico", "tamer.png"):
    shutil.copy(os.path.join(SRC, f_), base)
sys.path.insert(0, base)
import tamer as am
assert am.BASE_DIR == base

os.makedirs(am.DATA_DIR)
cfg = am.AppConfig()
s = cfg.servers[0]
s.update(install_dir=os.path.join(base, "srv"), rcon_port=29211, autostart=True, restart_warn_minutes="1",
         backup_interval_min=0)
cfg.data.update(discord_webhook=hook, update_check_min=0, mod_check_min=0)
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL)
os.makedirs(os.path.dirname(exe))
shutil.copy(os.path.join(HERE, "fake_ark_server.py"), exe)
os.chmod(exe, 0o755)
cfg.save()
fake_log = os.path.join(base, "fake.log")
os.environ["FAKE_ARK_LOG"] = fake_log

def wait(cond, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return
        time.sleep(0.5)
    print(open(am.Manager.log_path(s)).read() if os.path.exists(am.Manager.log_path(s)) else "(no log)")
    raise SystemExit(f"TIMEOUT: {what}")

def fake_cmds():
    return [l.strip()[4:] for l in open(fake_log)] if os.path.exists(fake_log) else []

# ---------------- 1. timed tasks in-process ----------------
m = am.Manager(cfg, lambda *a: None)
m.autostart_enabled = False
rt = m.runtime(s["id"])
m.run_op(s, "Start", m.op_start)
m.start_monitor()
wait(lambda: rt.online, 30, "online (tasks test)")
now = time.time(); nowdt = dt.datetime.now()
s["timed_tasks"] = [
    {"id": "a", "enabled": True, "kind": "broadcast", "mode": "interval", "every_min": 1, "text": "Hi {server} {players}/{max_players} on {map}"},
    {"id": "b", "enabled": True, "kind": "command", "mode": "times", "times": f"{nowdt:%H:%M}", "days": [nowdt.weekday()], "text": "SaveWorld\nDestroyWildDinos"},
    {"id": "c", "enabled": True, "kind": "chat", "mode": "times", "times": f"{nowdt:%H:%M}", "days": [(nowdt.weekday() + 1) % 7], "text": "wrong day"},
    {"id": "d", "enabled": False, "kind": "chat", "mode": "interval", "every_min": 1, "text": "disabled"},
]
m._run_due_tasks(s, rt, now)                 # interval tasks only start counting
rt.task_last["a"] = now - 61
rt.task_last["d"] = now - 61
m._run_due_tasks(s, rt, time.time())
time.sleep(2)
m._run_due_tasks(s, rt, time.time())         # must not re-fire
time.sleep(2)
cmds = fake_cmds()
print([c for c in cmds if c not in ("ListPlayers", "GetChat")])
assert cmds.count("Broadcast Hi My ARK Server 1 1/70 on The Island") == 1, cmds
assert cmds.count("SaveWorld") == 1 and cmds.count("DestroyWildDinos") == 1
assert not any("wrong day" in c or "disabled" in c for c in cmds)
assert set(rt.task_ran) == {"a", "b"}
print("timed tasks ok")
s["timed_tasks"] = []
m.run_op(s, "Stopping", m.op_stop, [])
wait(lambda: not m.is_running(s) and not rt.busy, 30, "stop after tasks test")
m.stop_event.set()
time.sleep(1)
posts.clear()

# ---------------- 2. service starts + autostarts ----------------
target = (dt.datetime.now() + dt.timedelta(minutes=3)).replace(second=0, microsecond=0)
s["restart_times"] = f"{target:%H:%M}"
cfg.save()
svc = subprocess.Popen([PY, "-I", os.path.join(base, "ark_manager.py"), "--service"], cwd=base)  # legacy launcher path
wait(lambda: am.service_info() is not None, 15, "service.json")
wait(lambda: any("Online" in p for p in posts), 40, "service Online post")
print("service up; restart target", target.strftime("%H:%M"))

# ---------------- 3. take over during countdown ----------------
def svc_status():
    r = am.service_request({"cmd": "status"})
    if not r: return {}
    try:
        st = r[0].recv(5)
    finally:
        r[0].close()
    return st or {}
wait(lambda: any("countdown" in b for b in svc_status().get("busy", [])), 100, "service countdown")
import tkinter as tk
assert am.acquire_gui_lock()
root = tk.Tk(); root.withdraw()
saw_wait = []
orig_recv = am.LineSocket.recv
def spy(self, timeout=None):
    msg = orig_recv(self, timeout)
    if msg and msg.get("status") == "waiting" and not saw_wait:
        saw_wait.append(msg)
        self.send({"cmd": "cancel"})  # same as pressing "Cancel countdowns"
    return msg
am.LineSocket.recv = spy
took = am.take_over_from_service(root)
am.LineSocket.recv = orig_recv
root.destroy()
print("takeover:", took, saw_wait)
assert took is True and saw_wait and "countdown" in saw_wait[0]["busy"][0]
r = am.service_request({"cmd": "status"}); st = r[0].recv(5); r[0].close()
assert st["paused"] is True, st
assert any("Restart cancelled" in p for p in posts), posts

# ---------------- 4. window engine adopts without re-announcing ----------------
cfg2 = am.AppConfig()
m2 = am.Manager(cfg2, lambda *a: None)
m2.autostart_enabled = False
s2 = cfg2.servers[0]
s2["restart_times"] = ""  # user clears the schedule in the window
cfg2.save()
m2.start_monitor()
rt2 = m2.runtime(s2["id"])
wait(lambda: rt2.online, 30, "window engine adopted + online")
n_online = sum("Online" in p for p in posts)
time.sleep(6)
assert sum("Online" in p for p in posts) == n_online == 1, posts
service_pid_server = rt2.pid
print("window engine manages pid", service_pid_server)

# ---------------- 5. window closes -> service resumes, handles crash ----------------
for x in cfg2.servers:
    m2.runtime(x["id"]).cancel_event.set()
m2.stop_event.set()
am.release_gui_lock()
wait(lambda: svc_status().get("paused") is False, 30, "service resume")
time.sleep(6)  # let it adopt
os.kill(service_pid_server, signal.SIGKILL)
wait(lambda: any("Crashed - restarting" in p for p in posts), 30, "service crash restart post")
wait(lambda: sum("Online" in p for p in posts) >= 2, 40, "back online after crash")
log = open(am.Manager.log_path(s)).read()
assert "Manager window opened - background service paused." in log
assert "Manager window closed - background service took over." in log
assert "Found already-running server process" in log

# ---------------- 6. shutdown ----------------
r = am.service_request({"cmd": "shutdown"})
msg = r[0].recv(10); r[0].close()
assert msg["status"] == "ready"
svc.wait(15)
assert am.service_info() is None
procs = am.scan_server_processes()
assert procs, "game server must keep running after the service exits"
for pid, _e, _c in procs:
    os.kill(pid, signal.SIGKILL)
print("POSTS:", posts)
print("ALL OK")
