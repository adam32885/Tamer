import os, shutil, sys, tempfile, time
sys.path.insert(0, sys.argv[1]); os.environ["FAKE_ARK_LOG"] = __import__("os").path.join(__import__("tempfile").gettempdir(), "fk_f4.log")
if os.path.exists(__import__("os").path.join(__import__("tempfile").gettempdir(), "fk_f4.log")): os.remove(__import__("os").path.join(__import__("tempfile").gettempdir(), "fk_f4.log"))
import tamer as am
# ---- staggered times + event arg
assert am.staggered_times("04:00, 16:00", 25) == "04:25, 16:25"
assert am.staggered_times("23:50", 20) == "00:10"
tmp = tempfile.mkdtemp()
cfg = am.AppConfig(os.path.join(tmp, "c.json")); cfg.data.update(update_check_min=0, mod_check_min=0)
cfg.servers.clear()
for i in range(3):
    s = am.default_server(i + 1, cfg.servers)
    s.update(install_dir=os.path.join(tmp, f"srv{i}"), port=27900 + i * 2, rcon_port=29600 + i, backup_interval_min=0)
    cfg.servers.append(s)
    exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe))
    shutil.copy("fake_ark_server.py", exe); os.chmod(exe, 0o755)
s1, s2, s3 = cfg.servers
s1["active_event"] = "WinterWonderland"
m = am.Manager(cfg, lambda *a: None)
assert "-ActiveEvent=WinterWonderland" in m.build_command(s1) and not any("ActiveEvent" in a for a in m.build_command(s2))
print("helpers ok")

# ---- start one at a time
m.start_monitor()
t0 = time.time(); m.start_staggered([s1, s2, s3])
time.sleep(1)
assert m.runtime(s2["id"]).queued and m.runtime(s3["id"]).queued
time.sleep(5)
states = {s["name"]: m.runtime(s["id"]).state for s in cfg.servers}; print(states)
assert states["Server 3"] == "Queued to start"
online_at, started_at = {}, {}
end = time.time() + 90
while time.time() < end and len(online_at) < 3:
    for s in cfg.servers:
        rt = m.runtime(s["id"])
        if rt.start_time and s["name"] not in started_at: started_at[s["name"]] = rt.start_time
        if rt.online and s["name"] not in online_at: online_at[s["name"]] = time.time()
    time.sleep(0.3)
print({k: round(v - t0, 1) for k, v in started_at.items()}, {k: round(v - t0, 1) for k, v in online_at.items()})
assert started_at["Server 2"] >= online_at["Server 1"] - 0.6 and started_at["Server 3"] >= online_at["Server 2"] - 0.6
end = time.time() + 10
while m.start_queue_active and time.time() < end: time.sleep(0.3)
assert not m.start_queue_active
print("staggered start ok")

# ---- broadcast to all (server 3 offline)
m.run_op(s3, "Stop", m.op_stop, []); time.sleep(8)
sent, skipped = m.broadcast_all("Cluster event at 9pm!")
assert sorted(sent) == ["Server 1", "Server 2"] and skipped == ["Server 3"], (sent, skipped)
time.sleep(0.5)
assert open(__import__("os").path.join(__import__("tempfile").gettempdir(), "fk_f4.log")).read().count("cmd Broadcast Cluster event at 9pm!") == 2
print("broadcast ok")

# ---- queue cancel (Stop all)
m.start_staggered([s3]); m.cancel_start_queue(); time.sleep(4)
print("after cancel:", m.runtime(s3["id"]).state)

# ---- wipe
mdir = m.map_save_dir(s1); os.makedirs(mdir, exist_ok=True)
for f in ("TheIsland_WP.ark", "TheIsland_WP_01.11.2026_04.00.00.ark", "123.arkprofile", "9.arktribe"):
    open(os.path.join(mdir, f), "w").write("x")
cdir = cfg.data["cluster_dir"]; os.makedirs(cdir, exist_ok=True); open(os.path.join(cdir, "eos1"), "w").write("c")
m.op_wipe(s1, "wild")
time.sleep(0.5); assert "cmd DestroyWildDinos" in open(__import__("os").path.join(__import__("tempfile").gettempdir(), "fk_f4.log")).read()
m.op_wipe(s1, "world", start_after=True)
left = sorted(os.listdir(mdir)); print("after world wipe:", left)
assert left == ["123.arkprofile", "9.arktribe"] and m.is_running(s1)
assert any("pre-wipe" in p for p in m.list_backups(s1))
time.sleep(4)
m.op_wipe(s1, "all", wipe_cluster=True)
assert os.listdir(mdir) == [] and os.listdir(cdir) == [] and not m.is_running(s1)
# undo by restoring the pre-wipe backup
newest_pre = [p for p in m.list_backups(s1) if "pre-wipe" in p][0]
m._restore(s1, newest_pre, False)
print("restored:", sorted(os.listdir(mdir)))
assert "123.arkprofile" in os.listdir(mdir)
print("wipe ok")
for s in cfg.servers:
    if m.is_running(s): m.run_op(s, "Stop", m.op_stop, [])
time.sleep(9); m.stop_event.set(); print("ALL OK")
