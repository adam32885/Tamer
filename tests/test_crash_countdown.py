import os, shutil, signal, sys, tempfile, time
sys.path.insert(0, sys.argv[1]); os.environ["FAKE_ARK_LOG"] = __import__("os").path.join(__import__("tempfile").gettempdir(), "fk.log")
import tamer as am, fakes
tmp = tempfile.mkdtemp(); cfg = am.AppConfig(os.path.join(tmp, "c.json")); s = cfg.servers[0]
s.update(install_dir=os.path.join(tmp, "srv"), rcon_port=29311, backup_interval_min=0)
cfg.data.update(update_check_min=0, mod_check_min=0)
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe))
fakes.install_server(exe)
m = am.Manager(cfg, lambda *a: None); rt = m.runtime(s["id"])
m.run_op(s, "Start", m.op_start); m.start_monitor()
t0 = time.time()
while not rt.online and time.time() - t0 < 30: time.sleep(0.5)
m.run_op(s, "Restarting", m.op_restart, False, [5], None, "test")  # 5-minute countdown
time.sleep(3); assert rt.countdown_until
old = rt.pid; fakes.crash(old); t1 = time.time()
while not (rt.pid and rt.pid != old and rt.online) and time.time() - t1 < 40: time.sleep(0.5)
print("\n".join(list(rt.log)[-6:]))
assert rt.pid != old and rt.online, "should be back up long before the 5-minute countdown"
print(f"back online in {time.time() - t1:.0f}s"); m.run_op(s, "Stop", m.op_stop, []); time.sleep(8); print("ALL OK")
