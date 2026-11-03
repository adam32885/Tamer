# What's new in Tamer

Newest first. Each section is also the "What's new" text for that version's GitHub release.

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
