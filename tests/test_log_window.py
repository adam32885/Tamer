"""ARK's "ASA ..." log window gets hidden (plain start and through AsaApi), other windows are left alone,
and unticking the setting shows it again. Windows only: it's about real windows."""
import ctypes, os, sys, tempfile, time
if os.name != "nt":
    print("Windows only - skipped"); print("ALL OK"); sys.exit(0)
import ctypes.wintypes as wt

tmp = tempfile.mkdtemp()
os.environ.update(FAKE_ARK_WINDOWS="1", FAKE_ARK_LOG=os.path.join(tmp, "fk.log"))
sys.path.insert(0, sys.argv[1])
import tamer as am, fakes

cfg = am.AppConfig(os.path.join(tmp, "c.json"))
cfg.data.update(update_check_min=0, mod_check_min=0)
s = cfg.servers[0]
s.update(install_dir=os.path.join(tmp, "srv"), rcon_port=29911, port=28311, backup_interval_min=0)
exe = os.path.join(s["install_dir"], am.SERVER_EXE_REL); os.makedirs(os.path.dirname(exe)); fakes.install_server(exe)
m = am.Manager(cfg, lambda *a: None); rt = m.runtime(s["id"])
u = ctypes.windll.user32


def wait(cond, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return
        time.sleep(0.25)
    print("\n".join(rt.log)); raise SystemExit(f"TIMEOUT waiting for {what}")


def windows(pid):
    """{title: visible} for the fake server's two windows."""
    out = {}
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(h, _):
        p = wt.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            t = ctypes.create_unicode_buffer(256); u.GetWindowTextW(h, t, 256)
            if t.value.startswith("ASA ") or t.value == "Some other window":
                out["ASA" if t.value.startswith("ASA ") else "other"] = bool(u.IsWindowVisible(h))
        return True
    u.EnumWindows(each, 0)
    return out


def server_pid():
    return rt.stats_pid or rt.pid


def run(label):
    t0 = time.time()
    m.run_op(s, "Start", m.op_start)
    wait(lambda: m.is_running(s) and (not s.get("asaapi") or rt.stats_pid), 40, f"{label}: running")
    wait(lambda: windows(server_pid()).get("other") is not None, 20, f"{label}: fake windows open")
    wait(lambda: windows(server_pid()) == {"ASA": False, "other": True}, 10, f"{label}: ASA window hidden")
    print(f"{label}: log window hidden {time.time() - t0:.1f}s after start, other window still showing")
    assert sum("Hid ARK's log window" in line for line in rt.log) == 1, "logged once"

    s["hide_log_window"] = False                          # unticked: it comes back
    wait(lambda: windows(server_pid()) == {"ASA": True, "other": True}, 12, f"{label}: shown again")
    s["hide_log_window"] = True                           # ticked again: hidden again by the regular check
    wait(lambda: windows(server_pid()) == {"ASA": False, "other": True}, 12, f"{label}: hidden again")
    print(f"{label}: setting off shows it, on hides it")

    m.run_op(s, "Stop", m.op_stop, [])
    wait(lambda: not m.is_running(s) and not rt.busy, 40, f"{label}: stop")
    rt.log.clear()


m.start_monitor()
run("plain start")

p = am.asaapi_paths(s)                                    # now through the pretend AsaApiLoader
os.makedirs(p["api_dir"], exist_ok=True)
open(p["loader"], "wb").write(fakes.loader_bytes()); open(p["dll"], "w").write("x")
s["asaapi"] = True
run("AsaApi start")

m.stop_event.set()
print("ALL OK")
