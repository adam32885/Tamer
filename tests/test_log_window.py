"""ARK's log window (Unreal's FConsoleWindow) stays for servers without AsaApi (and comes back if it was hidden),
and gets hidden only for servers started through AsaApi; other windows are left alone,
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
    print("\n".join(rt.log))
    for pid in (rt.stats_pid, rt.pid):                    # don't leave a pretend server holding the test ports
        if pid: fakes.crash(pid)
    raise SystemExit(f"TIMEOUT waiting for {what}")


def windows(pid):
    """{"ASA": visible, "other": visible} for the fake server's log window and its AsaApi-style console."""
    out = {}
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(h, _):
        p = wt.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            c = ctypes.create_unicode_buffer(256); u.GetClassNameW(h, c, 256)
            if c.value in ("FConsoleWindow", "ConsoleWindowClass"):
                out["ASA" if c.value == "FConsoleWindow" else "other"] = bool(u.IsWindowVisible(h))
        return True
    u.EnumWindows(each, 0)
    return out


def server_pid():
    return rt.stats_pid or rt.pid


def start(label):
    m.run_op(s, "Start", m.op_start)
    wait(lambda: m.is_running(s) and (not s.get("asaapi") or rt.stats_pid), 40, f"{label}: running")
    wait(lambda: windows(server_pid()).get("other") is not None, 20, f"{label}: fake windows open")


def stop(label):
    m.run_op(s, "Stop", m.op_stop, [])
    wait(lambda: not m.is_running(s) and not rt.busy, 40, f"{label}: stop")
    rt.log.clear()


m.start_monitor()

# ---------- without AsaApi: ARK's window is the only one, so it stays ----------
start("plain start")
time.sleep(7)                                             # longer than one regular 5 s check
assert windows(server_pid()) == {"ASA": True, "other": True}, windows(server_pid())
assert not any("Hid ARK's log window" in line for line in rt.log), "not hidden without AsaApi"
print("plain start: ARK's log window stays")
for h in am.ark_log_windows([server_pid()]):              # hidden earlier, e.g. by an older Tamer before a restart -
    am.show_window(h, False)                              # so this Tamer has no record of hiding it
assert windows(server_pid())["ASA"] is False and not rt.hidden_windows
wait(lambda: windows(server_pid()) == {"ASA": True, "other": True}, 12, "plain start: hidden window comes back")
assert any("Showing ARK's log window" in line for line in rt.log), list(rt.log)
print("plain start: a window hidden before a restart comes back by itself")
stop("plain start")

# ---------- through the pretend AsaApiLoader: hidden, and the tick box still works ----------
p = am.asaapi_paths(s)
os.makedirs(p["api_dir"], exist_ok=True)
open(p["loader"], "wb").write(fakes.loader_bytes()); open(p["dll"], "w").write("x")
s["asaapi"] = True
t0 = time.time()
start("AsaApi start")
wait(lambda: windows(server_pid()) == {"ASA": False, "other": True}, 10, "AsaApi start: ASA window hidden")
print(f"AsaApi start: log window hidden {time.time() - t0:.1f}s after start, the other window still showing")
assert sum("Hid ARK's log window" in line for line in rt.log) == 1, "logged once"
s["hide_log_window"] = False                              # unticked: it comes back
wait(lambda: windows(server_pid()) == {"ASA": True, "other": True}, 12, "AsaApi start: shown again")
s["hide_log_window"] = True                               # ticked again: hidden again by the regular check
wait(lambda: windows(server_pid()) == {"ASA": False, "other": True}, 12, "AsaApi start: hidden again")
s["asaapi"] = False                                       # AsaApi switched off: ARK's window comes back
wait(lambda: windows(server_pid()) == {"ASA": True, "other": True}, 12, "AsaApi off: shown again")
print("AsaApi start: the tick box hides/shows it, and switching AsaApi off brings it back")
stop("AsaApi start")

m.stop_event.set()
print("ALL OK")
