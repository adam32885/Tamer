# Tamer - "Tame your server"

A Windows desktop app for running ARK: Survival Ascended dedicated servers, including multi-map clusters. One person maintains it, for their own servers. It was first built in a claude.ai chat (v1.0 to v1.11.2) and moved here so changes can be run and tested on real Windows with a real ARK server.

## Ground rules
- **Python 3 standard library only.** Use tkinter/ttk, urllib, socket, ctypes and so on, with no pip dependencies, so Tamer runs from a plain Python install and builds into a single exe.
- **Keep everything in `tamer.py`.** `ark_manager.py` is only a compatibility shim for the old name.
- **Never block the UI thread.** Network and disk work runs in a `threading.Thread`, then hands results back with `self.q.put(("call", None, fn))` (also `("info"|"error", None, text)`). `App._pump` drains the queue on the Tk thread.
- **Write for someone who isn't a programmer.** Error messages say what happened and what to do next, in plain words. Add a README section for every user-facing feature.
- **Bump `APP_VERSION`** for each change the user receives.
- **Don't put test data in the real folder.** User data lives next to `tamer.py`: `manager_data/` (config.json, logs, service.json, gui.lock), plus `servers/`, `backups/` and `cluster/` by default. Run the tests with `tests/run_tests.py`, which works on a throwaway copy of the app in the temp folder.

## Layout of tamer.py (search by name; line numbers move)
- **Constants:** paths inside a server install (`SERVER_EXE_REL`, `CONFIG_REL`, `GAMELOG_REL`), `MAPS`, the CurseForge settings (`CF_*`, game id 83374), and the `CMD_FLAG_GROUPS` behind the Command line tab.
- **Helpers:** INI read/write (`ini_get`/`ini_set`), Windows process APIs through ctypes (`pid_alive`, `process_stats`, `apply_process_cpu`) and scheduling (`parse_times`, `staggered_times`, `next_occurrence`).
- **`RconClient`** speaks Source RCON. `parse_players` parses its player list.
- **`CurseForge`** handles mod search and lookups. With no key, or a key CurseForge rejects, it falls back to the free proxy at api.curse.tools. The `ASM_CF_BASE` environment variable overrides the address for tests.
- **`DiscordNotifier`** sends webhook embeds.
- **`AppConfig`** loads and saves `manager_data/config.json`. `default_server()` defines every per-server setting.
- **`Manager`** is the engine, with no GUI: start, stop and restart (with countdown warnings); `build_command`/`to_cmdline`; crash detection and auto-restart; SteamCMD install and update; "Update all", run one server at a time; backups and the second backup copy; the mod-update watcher; the memory-limit restart; timed tasks; and staggered start and restart.
- **`diagnose_server`** is the Troubleshoot button, driven by `LOG_PATTERNS`. **`check_connectivity`** covers ports, the firewall, `UPnP`, the public IP and BattleMetrics.
- **AsaApi:** `asaapi_*`, `list_plugins`, `install_plugin_zip` and `set_plugin_enabled`. Servers start through `Win64\AsaApiLoader.exe`, and Tamer tracks the real server process it launches.
- **Background service:** `ServiceAgent`/`run_service` run `tamer.py --service` as a Task Scheduler S4U task. The window and the service hand control back and forth through `gui.lock` and a localhost control socket (`service.json`).
- **`App`** is the tkinter GUI. It holds the server list plus tabs: Server, Command line, Game settings, Mods, Plugins, Players, Automation, Messages, Performance and Log. `FlowFrame` wraps button rows when the window is narrow. `ScrollFrame` makes tabs scrollable. `apply_ttk_theme` handles light and dark mode.

## How ARK is launched
`ArkAscendedServer.exe <Map>?SessionName=..?Port=..?QueryPort=..?RCONEnabled=True?RCONPort=..?...?ServerAdminPassword=.. -flags`
- The `?options` go in the map string, with `ServerAdminPassword` last, followed by the `-flags`.
- `-mods=` keeps the load order.
- Passive mods (`passive_mods` in the server's settings) must also be listed in `-mods`, ahead of the rest, and are named again in `-passivemods=`.
- Cluster settings come from Settings: `-clusterid`, plus `-ClusterDirOverride`.
- SteamCMD installs app 2430930.

## Testing
`python tests/run_tests.py` runs everything this OS supports. `python tests/run_tests.py gui_passive test_cfkey` runs the named tests. Each test is a standalone script taking `<app folder> <screenshot folder>`.
- **Logic and GUI tests** (`test_core`, `test_urls`, `test_bm`, `test_cfkey`, `test_mods` and `gui_*`) run anywhere. The GUI tests drive the real `App` and stub `messagebox` so dialogs don't block. A test that hangs is usually waiting on a dialog that isn't stubbed.
- **Process tests** (`test_cmdline`, `test_crash_countdown`, `test_automation`, `test_diag_net`, `test_update_all`, `test_f4`, `test_asaapi`, `test_mod_wait`) start a pretend server through `tests/fakes.py`. On Windows that builds one real exe with PyInstaller (test-only, cached in the temp folder) which acts as both `ArkAscendedServer.exe` and `AsaApiLoader.exe`. `test_tasks_service` still doesn't run on Windows.
- Tests must never run a real install: stub `ensure_steamcmd` or `_update`, because on Windows the real ones download SteamCMD and ARK. Opening `App` with `autostart` on does this too, since auto-starting a server that isn't installed installs it.
- Screenshots need ImageMagick's `import` (Linux). Without it they are skipped.
- The tests were written on Linux under Xvfb. **Not yet verified on real Windows:** the tray icon, the Task Scheduler service and UAC prompts, the real AsaApiLoader, firewall rules and the GitHub release download. These are the most likely places for Windows bugs.

## Things learned the hard way
- **CurseForge proxy:** the base URL is `https://api.curse.tools/v1/cf`, with paths `/mods/search` and `/mods`. A doubled `/v1` gives 404.
- **CurseForge keys** are 60 characters and start with `$2a$10$`. A 403 means the key is bad or revoked. Tamer cleans up pasted keys, has a Test key button, and falls back to the proxy when a key is rejected.
- **BattleMetrics** needs a free token (setting `battlemetrics_token`). Without one, the API returns 403.
- **UI layout:** narrow windows used to cut off the tables. Use paned windows (`initial_sash`) and `FlowFrame` button rows, and check `gui_small` after changing layout.
- **Update all:** a failed update must not leave a server stopped. Restore the server and carry on with the next one.

## Build
`build_exe.bat` runs PyInstaller (`--name Tamer --icon tamer.ico --add-data` for the icons). `Start Tamer.bat` runs it from source.

`build_installer.bat` builds the exe, then the installer from `installer/tamer.iss` (Inno Setup 6), passing `APP_VERSION` from `tamer.py`. The result is `installer/Output/Tamer-Setup-<version>.exe`.
- The install is per-user, into `AppData\Local\Programs\Tamer` with no admin prompt, because Tamer writes its data next to `Tamer.exe`. Program Files would be read-only.
- Never change `AppId` in `tamer.iss`: newer installers find older installs through it.
- The installer's "Start with Windows" writes the same `Startup\Tamer.bat` as `set_start_with_windows`. Keep the two in step.
- Uninstall never deletes data (manager_data, servers, backups).
- To test it, install silently into a temp folder (`/VERYSILENT /DIR=... /TASKS=...`), then run `unins000.exe /VERYSILENT`.
