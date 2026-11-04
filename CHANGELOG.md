# What's new in Tamer

Newest first. Each section is also the "What's new" text for that version's GitHub release.

## 1.21.1
- **Tamer now has a Discord** for questions and help: https://discord.gg/nj7tkY53gq. Open it with the **💬 Get help on Discord** link under **☕ Support Tamer** in the top-right corner, or **Help > Get help on Discord**.
- The Mods tab's **installed list is no longer squeezed** to a row or two on smaller windows and bigger text. It now has the whole right side to itself. **Details** moved under the search results (drag the line between them to resize), and the tip about restarting and passive mods shows in the Details box until you pick a mod. The Up / Down buttons are now **▲ / ▼**.

## 1.21.0
- **Rearrange your servers:** drag them up or down in the list, or use the **▲ / ▼** arrows next to "Servers" (or Ctrl+Up / Ctrl+Down). The order is saved, and Start all, Update all and auto-start follow it.
- Fixed: updating could stop with "DeleteFile failed; code 5. Access is denied" because Tamer was still running. It might be waiting on a question, sitting in the tray, or running as the background service. Now Tamer closes without asking anything when it updates, and stops the background service first (letting a running backup or update finish). The installer also closes any Tamer.exe still running from its folder, then starts the background service again if it's installed. This also fixes updates started from older versions.
- **Bigger text, and a Text size setting:** File > Settings > General > Text size offers Normal (the old size), Large (the new default) and Larger. Everything grows together and changes straight away.
- Shorter tab names, so all ten fit at the bigger sizes on laptop screens too: **Command line** is now **Launch**, **Game settings** is now **Game**, **Automation** is now **Schedule** and **Performance** is now **Stats**. Everything inside them is the same.
- Server names can now contain `"` quote marks. ARK can't read straight quotes inside its launch line, so Tamer passes them as curly quotes (The “Best” Server), which look the same in the server list. Passwords still can't contain `"` or `?`, and the welcome now checks that too.

## 1.20.0
- **Mod settings:** a new tab under Game settings for the settings mods read from GameUserSettings.ini. It lists each mod's section (such as `[StructuresPlus]`) with a best guess at which installed mod it belongs to, and its settings. You can edit, add and remove settings and sections. Only what you change is rewritten, and it stays in step with Common settings and the raw INI editor.
- **Check for updates** link in the top-right corner, next to Ko-fi. The green **⬆ Update to x.y.z** link takes its place when there's an update.
- **Help > Send a bug report...** makes one zip file to attach to a GitHub issue: Tamer's version, your Windows version, a summary of each server, and Tamer's settings and logs, plus each server's ShooterGame.log if you tick the box. Every password, API key, token and Discord webhook is removed first, and nothing is sent anywhere. It then opens the GitHub bug report form for you.
- **Bug report and feature request forms** on GitHub (New issue), so reports include what's needed to fix them.

## 1.18.3
- Fixed: importing a server whose launch line uses `\"` as its quotes, such as `SessionName=\"JAG(Just A Game) The Island\"` with no other quotes around it, cut the name at the first space (`"JAG(Just`). Tamer now reads it the way ARK does and gets the whole name. Servers already imported this way need their name fixed by hand on the Server tab, or importing again.

## 1.18.2
- **Download and install** now shows a progress window ("Downloading Tamer… 4.3 of 15.0 MB") with a **Cancel** button, instead of a silent wait. If the download or the installer can't start, Tamer says why and offers the release page. Each step is written to `manager_data\logs\update.log`.
- Fixed: without your own CurseForge API key, the Mods tab could show "(loading...)" for every installed mod, and the mod update check quietly stopped noticing new versions. The free CurseForge service Tamer uses stopped answering requests for several mods at once. Tamer now fetches them one at a time when that happens (41 mods take a few seconds). If a name really can't be found, the row says "(name not found - click Refresh)" and the reason goes to the Log tab.
- Fixed: after removing all your servers, reopening Tamer made a new blank "Server 1". Now the list stays empty and the welcome opens, so you can set up a server or import one, or click Skip.

## 1.18.1
- Fixed: after **Download and install**, the newly installed Tamer could fail to open with "Failed to load Python DLL". The update itself always worked, and opening Tamer from the Start menu was fine. Now it opens by itself, even when updating from an older version.
- Fixed: ARK's log window was hidden for servers that don't use AsaApi too (such as imported ones), which left them with no window at all. Now it's only hidden for servers started with AsaApi. A window that's already hidden comes back by itself.
- Fixed: importing a server whose launch line wraps values in escaped quotes (`\"`) left stray backslashes in its name and map, such as `\TheIsland_WP\`. Tamer now reads launch lines exactly the way Windows does.

## 1.18.0
- **Import an existing server:** File > Import existing server brings in a server you set up by hand, with a .bat file or with another manager. Pick it while it's running, pick its .bat file, or just its folder. Tamer reads the map, name, ports, passwords, mods (in order, including passive mods), cluster, flags and options, shows you a preview first, and keeps every INI setting and save, because the server stays in its own folder. The welcome links to it too.

## 1.17.1
- The update window shows release notes as plain text, without the asterisks and other formatting marks.

## 1.17.0
- **Welcome for new users:** the first time Tamer opens, a short step-by-step setup picks where to keep your servers (the drive with the most free space), sets up your first server's name, map, players and ports, and can start the install straight away. Run it again any time from **Help > Run the welcome again** to add another server.
- New servers go in the folder you picked in the welcome, instead of inside Tamer's own folder.
- The server list no longer squeezes the tab names on smaller windows. When space is tight, the Name and Map columns give way, and Status and Players always fit.

## 1.16.0
- **Tamer updates itself:** it checks for a new version once a day. When there is one, a green **⬆ Update to x.y.z** link appears in the top-right corner. Click it to see what's new and choose **Download and install**. Your settings are kept and your servers keep running. You can also use **Help > Check for Tamer updates now**, or switch the daily check off in **File > Settings > General**.
- The server list columns fit at any Windows display scaling. "Not installed" and "Players" were cut off at 150%.
- Tamer is now open source under the MIT licence.

## 1.15.2
- A **☕ Support Tamer** link to Ko-fi in the top-right corner, and in the **Help** menu.

## 1.15.1
- **Windows installer:** `Tamer-Setup-<version>.exe` installs Tamer just for you, with no admin prompt. It adds a Start menu entry and offers a desktop shortcut and start-with-Windows. Uninstalling keeps your settings, servers and backups.
- Hiding ARK's own log window now finds the real window. 1.15.0 looked for the wrong title and missed it.

## 1.15.0
- **Hide ARK's log window** (Server tab > Behaviour, on by default): only the AsaApi window shows for servers started with plugins. The server log is on Tamer's Log tab. Untick the box to bring the window back.

## 1.14.2
- **Plugins folder** button on the Plugins tab. The old "Open folder" button is now **Selected plugin's folder**.

## 1.14.1
- Scrolling up on a page that already fits the window no longer leaves an empty gap at the top.

## 1.14.0
- Tamer's green in light and dark mode: green main buttons (Start, Install / Update, Save...), coloured status dots in the server list, and green headings.

## 1.13.2
- The date columns on the Mods tab are no longer cut off, and the Active / Passive circles line up under their headings.

## 1.13.1
- The File / Help menu bar follows dark mode, and the window shows Tamer's own icon. Alt+F and Alt+H open the menus.

## 1.13.0
- **Copy to other servers:** copy one server's mods, game settings and Tamer settings to others, without changing their names, ports or passwords. A backup of each changed file is kept.

## 1.12.0
- **Wait for an empty server** before a mod update restart, with an optional time limit.

## 1.11.4
- Active and Passive mods are shown as tick circles in the installed mods list.

## 1.11.3 and earlier
- Built before Tamer had a version history here: server install and updates through SteamCMD, clusters, mods from CurseForge, AsaApi plugins, backups, schedules, Discord alerts, crash restarts, the troubleshooter, performance graphs and the background service.
