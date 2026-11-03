import os, shutil, sys, tempfile, threading, time
sys.path.insert(0, sys.argv[1]); os.environ["FAKE_ARK_LOG"] = __import__("os").path.join(__import__("tempfile").gettempdir(), "fk_ua.log")
import tamer as am
tmp = tempfile.mkdtemp()
cfg = am.AppConfig(os.path.join(tmp, "c.json")); cfg.data.update(update_check_min=0, mod_check_min=0)
cfg.servers.clear()
for i in range(3):
    s = am.default_server(i + 1, cfg.servers)
    s.update(install_dir=os.path.join(tmp, f"srv{i}"), port=27800 + i * 2, rcon_port=29500 + i, backup_interval_min=0,
             restart_warn_minutes="1")
    cfg.servers.append(s)
    exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe))
    shutil.copy("fake_ark_server.py", exe); os.chmod(exe, 0o755)
    os.makedirs(os.path.join(s["install_dir"], "steamapps"))
    open(os.path.join(s["install_dir"], "steamapps", f"appmanifest_{am.ASA_APP_ID}.acf"), "w").write(
        '"AppState"\n{\n "buildid" "%s"\n}\n' % ("200" if i == 2 else "100"))
s1, s2, s3 = cfg.servers
m = am.Manager(cfg, lambda *a: None)
m.fetch_latest_build = lambda: "200"
events, down_at_once = [], []
def fake_update(s, validate=False):
    running_others = [o["name"] for o in (s1, s2) if o is not s and not m.is_running(o)]
    down_at_once.append(running_others)
    events.append(("update-start", s["name"]))
    time.sleep(2)
    if s is s2:
        raise RuntimeError("SteamCMD exited with code 8")
    open(os.path.join(s["install_dir"], "steamapps", f"appmanifest_{am.ASA_APP_ID}.acf"), "w").write('"buildid" "200"')
    events.append(("update-end", s["name"]))
m._update = fake_update
m.start_monitor()
for s in (s1, s2):
    m.run_op(s, "Start", m.op_start)
end = time.time() + 40
while time.time() < end and not all(m.runtime(s["id"]).online for s in (s1, s2)): time.sleep(0.5)
assert all(m.runtime(s["id"]).online for s in (s1, s2))
pids = {s["name"]: m.runtime(s["id"]).pid for s in (s1, s2)}
log = []
res = m.update_all(cfg.servers, warn=False, progress=lambda s, st: log.append((s["name"], st)))
for k, v in res.items(): print(cfg.get(k)["name"], "->", v)
print(events); print("other servers down during each update:", down_at_once)
assert res[s1["id"]].startswith("Done - build 200")
assert res[s2["id"]].startswith("Failed: SteamCMD exited with code 8 (started the old version)")
assert res[s3["id"]] == "Up to date (build 200)"
assert down_at_once == [[], []], "only the server being updated may be down"
i1 = next(i for i, (n, st) in enumerate(log) if n == "Server 1" and st.startswith("Done"))
i2 = next(i for i, (n, st) in enumerate(log) if n == "Server 2" and st == "Stopping")
assert i1 < i2, "server 2 must wait for server 1 to finish (incl. back online)"
assert any(st.startswith("Waiting for it to come back online") for n, st in log if n == "Server 1")
for s in (s1, s2):
    rt = m.runtime(s["id"]); assert m.is_running(s) and rt.online and rt.pid != pids[s["name"]] and rt.busy is None
print("sequential update ok")

# cancel during the warning countdown: servers stay up, the rest is cancelled
for s in (s1, s3): open(os.path.join(s["install_dir"], "steamapps", f"appmanifest_{am.ASA_APP_ID}.acf"), "w").write('"buildid" "100"')
cancel = threading.Event(); log2 = []
t = threading.Thread(target=lambda: log2.append(m.update_all(cfg.servers, warn=True, cancel=cancel,
                                                              progress=lambda s, st: log2.append((s["name"], st)))))
t.start(); time.sleep(4)
print(log2[-1])
assert any("Warning players" in st for n, st in log2[:-0 or None] if isinstance(st, str) and n == "Server 1")
cancel.set(); m.runtime(s1["id"]).cancel_event.set()
t.join(20); res2 = log2[-1]
print(res2 and {cfg.get(k)["name"]: v for k, v in res2.items()})
assert res2[s1["id"]] == "Cancelled (servers left running)" and res2[s2["id"]] == "Cancelled" and res2[s3["id"]] == "Cancelled"
assert m.is_running(s1) and m.runtime(s1["id"]).pid == m.runtime(s1["id"]).pid and m.runtime(s1["id"]).busy is None
print("cancel ok")
for s in (s1, s2): m.run_op(s, "Stop", m.op_stop, [])
time.sleep(9); m.stop_event.set(); print("ALL OK")
