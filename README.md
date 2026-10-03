# Lost Island for Archcraft Sway

A compact, black dynamic island for Sway, maintained by [byte4day](https://github.com/byte4day). This is a customized Linux build of [Marco Zorn's Lost Island v1.7.2](https://github.com/MarcoZorn/lost-island/tree/v1.7.2), with its MIT license and original attribution preserved. It is designed for Archcraft, and should also work on Arch Linux with Sway and GTK4 layer shell.

The idle pill shows the Arch mark and clock. When an MPRIS player is playing, it shows the track and album art. The expanded card has playback controls, Wi-Fi, Bluetooth, speaker and microphone switches, battery, volume, a focus timer, and small launchers for the installed Claude Code, Codex, and Cursor Agent CLIs. The black and neutral-gray interface uses Material Symbols and restrained grayscale brand artwork.

**Screen recording:** Click **Record** to choose a display when more than one is connected, then choose **With audio** or **Without audio**. With audio captures the default output's system sound, not the microphone. Stop finalizes an MP4 in `~/Videos/Recordings/`. A recording indicator and timer remain visible on the pill.

## Requirements

- Sway on Wayland, Python 3.11 or newer, GTK4, libadwaita, PyGObject and GTK4 layer shell.
- Arch/Archcraft packages for the core interface and controls: `python`, `python-gobject`, `python-cairo`, `gtk4`, `gtk4-layer-shell`, `libadwaita`, `libpulse`, `networkmanager`, `bluez`, `bluez-utils`, `util-linux`, and `ttf-material-symbols-variable` (Archcraft also provides this font through `archcraft-fonts`).
- `wf-recorder` for screen recording; `pactl` from `libpulse` and a working PulseAudio/PipeWire output for system audio.
- Optional: `upower` for battery, `cava` for live EQ, `alacritty` for the CLI launchers, and the `claude`, `codex`, and `cursor-agent` commands for their respective buttons. Music requires an MPRIS-capable player.

On Arch Linux, install the repository packages with:

```sh
sudo pacman -S --needed python python-gobject python-cairo gtk4 gtk4-layer-shell libadwaita libpulse networkmanager bluez bluez-utils util-linux ttf-material-symbols-variable wf-recorder upower cava alacritty
```

NetworkManager, Bluetooth, and an audio server must already be configured for their controls to work. Installing the packages alone does not configure those system services.

## Install on Sway

This project runs from a user-owned checkout; it does not need `sudo pip`, an AUR build, or the upstream `lost-island` package. The service template assumes this checkout path:

```sh
git clone https://github.com/byte4day/lost-island-archcraft-sway.git "$HOME/.local/share/lost-island"
mkdir -p "$HOME/.config/systemd/user"
cp "$HOME/.local/share/lost-island/packaging/lost-island.service" "$HOME/.config/systemd/user/lost-island.service"
systemctl --user daemon-reload
systemctl --user enable --now lost-island.service
```

If you already have `~/.local/share/lost-island` or a user `lost-island.service`, back it up before cloning or copying the unit. If the upstream service is already running, restart it after installing this user unit: `systemctl --user restart lost-island.service`.

For Sway sessions that do not start `graphical-session.target`, add **one** startup command to your existing Sway startup file or config:

```sh
systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP
systemctl --user start lost-island.service
```

In a Sway config, use `exec sh -c 'systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP; systemctl --user start lost-island.service'`. In Archcraft's executable startup script, add the two commands after its other session setup. Do not add both methods. To replace an existing bar, back up its Sway config and remove or comment only that bar's startup command; do not stop network, tray, notification, or policy services just because they appeared beside the bar.

Open the card by clicking the pill. The gear opens settings. Settings are saved at `~/.config/lost-island/config.json`, which is created on first run; this file is intentionally absent from the repository. Change the island monitor, clock, modules, faces, and accent there or through the settings window. The default theme is opaque black with a neutral accent, and the automatic pill face returns to the clock when playback pauses.

## Use and checks

```sh
systemctl --user status lost-island.service
journalctl --user -u lost-island.service -n 50 --no-pager
PYTHONPATH="$HOME/.local/share/lost-island" python3 -m unittest discover -s "$HOME/.local/share/lost-island/tests" -v
```

The Claude, Codex, and Cursor buttons open their **installed terminal CLIs** through Alacritty. They do not install or sign in to those products. If a button says its command is missing, install that CLI through its official instructions and ensure its executable is on `PATH` or in `~/.local/bin`. This build uses `~/.config/sway/alacritty/alacritty.toml` when present and Alacritty's default configuration otherwise.

The recording picker lists connected display connectors from GTK. If you select **With audio** and the default output monitor disappears before recording starts, the recorder reports an error instead of silently saving a mute file. A short video-only test and a short video-plus-system-audio test were completed on the original Archcraft/Sway setup. `wf-recorder` usage is documented [upstream](https://github.com/ammen99/wf-recorder/blob/master/README.md).

## Prompt for an AI setup agent

Copy this prompt into a coding agent that has access to the target user's machine. It is written for an Archcraft or Arch Linux Sway session:

```text
Set up https://github.com/byte4day/lost-island-archcraft-sway for me as my Sway dynamic island. Read the repository README and inspect my current Sway configuration, startup files, user systemd units, existing bar, available monitors, audio service, package manager, and installed CLI tools before editing anything. Preserve my settings and back up any service or Sway files you change.

Install the documented Arch packages if missing. Clone the repository to ~/.local/share/lost-island (or update an existing checkout safely). Install the provided user systemd unit and ensure the Sway session starts it exactly once with WAYLAND_DISPLAY available. If I have an existing bar, replace only that bar's startup entry after checking what other services it launches; keep network, Bluetooth, tray, notifications, and policy services working. Set the island to the monitor I use and keep the black minimal theme. Do not copy another machine's config.json or credentials.

Verify the Arch pill, expanded controls, MPRIS music behavior, both display choices when I have multiple screens, and the recording setup's audio choices. Test that stopping a short recording produces a playable MP4, and remove that test file afterward. Check the Claude, Codex, and Cursor Agent buttons only against CLIs already installed for me; do not install or authenticate those services without asking. Run the repository tests and inspect systemd status and logs. Explain the files you changed, how to undo the setup, and any feature that could not be verified on my machine.
```

## Remove or revert

Stop and disable the user service with `systemctl --user disable --now lost-island.service`. Remove the Sway startup line you added, then restore your backed-up service and bar configuration if desired. Your settings are in `~/.config/lost-island/`, recordings are in `~/Videos/Recordings/`, and the checkout is in `~/.local/share/lost-island/`; remove these only if you no longer need their contents.

## Credits and license

The application started from [Lost Island](https://github.com/MarcoZorn/lost-island) by Marco Zorn, licensed under MIT; this repository retains the original copyright notice. The Arch mark is adapted from the installed Papirus icon theme. Claude, Codex, and Cursor artwork remains the property of its respective owners and is used only to identify the corresponding launcher. This project is an independent customization, not an official Apple, Anthropic, OpenAI, Cursor, or Archcraft product. See [LICENSE](LICENSE).
