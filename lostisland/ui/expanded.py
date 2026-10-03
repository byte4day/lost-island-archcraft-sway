"""The expanded card — media player up top, quick toggles and tiles below.

Every timer here lives only while the card is mapped: the 1 Hz seek tick,
the 3 s system sampler, the weather request. Unmapping tears it all down.
"""

from __future__ import annotations

import time
import weakref

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from lostisland.services.controls import SystemControls
from lostisland.services.recorder import system_audio_source
from lostisland.ui.draw import pick_icon
from lostisland.ui.launchers import LauncherRow

POMODORO = 25 * 60


class Expanded(Gtk.Box):
    def __init__(self, cfg: dict, media, power, on_timer_change=None,
                 weather=None, system=None, on_settings=None, recorder=None,
                 airplay=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        self.add_css_class("expanded")
        self.cfg = cfg
        self.media = media
        self.power = power
        self.weather = weather
        self.system = system
        self.on_timer_change = on_timer_change
        self.on_settings = on_settings
        self.recorder = recorder
        self.airplay = airplay

        self._pos_timer = 0
        self._seek_dragging = False
        self._position_us = 0
        self.controls = SystemControls()
        self._controls_timer = 0
        self._control_busy: set[str] = set()
        self.control_buttons: dict[str, Gtk.ToggleButton] = {}
        self.control_handlers: dict[str, int] = {}

        self._build_header()
        self._build_player()
        if cfg.get("modules", {}).get("toggles", True):
            self._build_toggles()
        self.append(LauncherRow())
        self._build_tiles()
        self._build_footer()

        if self.recorder is not None:
            self_ref = weakref.ref(self)

            def on_recorder_changed(*_):
                widget = self_ref()
                if widget is not None:
                    widget._sync_recorder()

            handler = self.recorder.connect("changed", on_recorder_changed)
            weakref.finalize(self, self.recorder.disconnect, handler)
            self._sync_recorder()

        if self.airplay is not None:
            self_ref = weakref.ref(self)

            def on_airplay_changed(*_):
                widget = self_ref()
                if widget is not None:
                    widget._sync_airplay()

            handler = self.airplay.connect("changed", on_airplay_changed)
            weakref.finalize(self, self.airplay.disconnect, handler)
            self._sync_airplay()

        self.connect("map", lambda *_: self._on_map())
        self.connect("unmap", lambda *_: self._on_unmap())

    # -- header: gear + connectivity chips ---------------------------------

    def _build_header(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        gear = Gtk.Button()
        gear.set_child(_symbol("settings"))
        gear.set_tooltip_text("Island settings")
        gear.add_css_class("chip-btn")
        gear.connect("clicked", lambda *_: self.on_settings and self.on_settings())
        spacer = Gtk.Box(hexpand=True)

        self.record_button = Gtk.Button()
        self.record_button.add_css_class("record-button")
        record_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.record_icon = _symbol("videocam")
        self.record_text = Gtk.Label(label="Record")
        record_content.append(self.record_icon)
        record_content.append(self.record_text)
        self.record_button.set_child(record_content)
        self.record_button.connect("clicked", self._on_record_clicked)
        self.record_button.set_visible(self.recorder is not None)

        self.airplay_button = Gtk.Button()
        self.airplay_button.add_css_class("record-button")
        self.airplay_button.add_css_class("airplay-button")
        airplay_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=5)
        airplay_content.append(_symbol("airplay"))
        self.airplay_text = Gtk.Label(label="AirPlay")
        airplay_content.append(self.airplay_text)
        self.airplay_button.set_child(airplay_content)
        self.airplay_button.set_visible(self.airplay is not None)
        self.airplay_button.connect("clicked", self._on_airplay_clicked)

        self.bt_chip = _chip("bluetooth-active-symbolic")
        self.net_chip = _chip("network-wireless-symbolic")

        row.append(gear)
        row.append(spacer)
        row.append(self.net_chip)
        row.append(self.bt_chip)
        row.append(self.airplay_button)
        row.append(self.record_button)
        self.append(row)

        self.airplay_status = Gtk.Label(xalign=0)
        self.airplay_status.add_css_class("record-status")
        self.airplay_status.set_visible(False)
        self.append(self.airplay_status)

        self.record_status = Gtk.Label(xalign=0)
        self.record_status.add_css_class("record-status")
        self.record_status.set_visible(False)
        self.append(self.record_status)

        self.record_setup = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                    spacing=9)
        self.record_setup.add_css_class("record-setup")
        self.record_setup.set_visible(False)
        self.append(self.record_setup)

        self.record_display_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                          spacing=10)
        self.record_display_row.append(Gtk.Label(label="Display", xalign=0,
                                                  hexpand=True))
        self.record_display_picker = None
        self.record_display_row.set_visible(False)
        self.record_setup.append(self.record_display_row)

        audio_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        audio_row.append(Gtk.Label(label="Audio", xalign=0, hexpand=True))
        self.with_audio = Gtk.CheckButton(label="With audio")
        self.with_audio.set_tooltip_text(
            "Capture sound playing through the default output")
        self.without_audio = Gtk.CheckButton(label="Without audio")
        self.without_audio.set_group(self.with_audio)
        self.with_audio.set_active(True)
        audio_row.append(self.with_audio)
        audio_row.append(self.without_audio)
        self.record_setup.append(audio_row)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("record-action")
        cancel.connect("clicked", lambda *_: self.record_setup.set_visible(False))
        start = Gtk.Button(label="Start recording")
        start.add_css_class("record-action")
        start.add_css_class("record-action--primary")
        start.connect("clicked", self._start_recording)
        actions.append(cancel)
        actions.append(start)
        self.record_setup.append(actions)

    def _on_record_clicked(self, *_):
        if self.recorder.running:
            self.recorder.stop()
        else:
            self._show_record_setup()

    def _on_airplay_clicked(self, *_):
        if self.airplay.running:
            self.airplay.stop()
        else:
            self.airplay.start()

    def _sync_airplay(self, *_):
        if self.airplay is None:
            return
        running = self.airplay.running
        self.airplay_button.set_sensitive(not self.airplay.stopping)
        self.airplay_button.set_tooltip_text(
            f"Connect to Lost Island from AirPlay; click to stop"
            if running else "Start UxPlay AirPlay receiver")
        self.airplay_text.set_label("AirPlay on" if running else "AirPlay")
        if running:
            self.airplay_button.add_css_class("airplay-button--active")
        else:
            self.airplay_button.remove_css_class("airplay-button--active")
        error = self.airplay.message.startswith(("UxPlay", "Could not"))
        self.airplay_status.set_visible(error)
        if error:
            self.airplay_status.set_label(self.airplay.message)

    def _show_record_setup(self):
        display = self.get_display()
        model = display.get_monitors() if display else None
        monitors = []
        if model is not None:
            for index in range(model.get_n_items()):
                monitor = model.get_item(index)
                connector = monitor.get_connector()
                if connector:
                    size = monitor.get_geometry()
                    monitors.append((connector,
                                     f"{connector} · {size.width} × {size.height}"))
        self.record_monitors = monitors
        if not monitors:
            self.record_status.set_label("No connected display is available")
            self.record_status.set_visible(True)
            self.record_setup.set_visible(False)
            return
        if self.record_display_picker is not None:
            self.record_display_row.remove(self.record_display_picker)
        self.record_display_picker = Gtk.DropDown.new_from_strings(
            [label for _, label in monitors])
        self.record_display_picker.set_selected(next(
            (i for i, (connector, _) in enumerate(monitors)
             if connector == self.cfg.get("monitor")), 0))
        self.record_display_row.append(self.record_display_picker)
        self.record_display_row.set_visible(len(monitors) > 1)

        audio_available = system_audio_source() is not None
        self.with_audio.set_sensitive(audio_available)
        self.with_audio.set_active(audio_available)
        self.without_audio.set_active(not audio_available)
        self.record_status.set_visible(False)
        self.record_setup.set_visible(True)

    def _start_recording(self, *_):
        index = self.record_display_picker.get_selected()
        if index >= len(self.record_monitors):
            self.record_status.set_label("Choose a display to record")
            self.record_status.set_visible(True)
            return
        connector = self.record_monitors[index][0]
        if self.recorder.start(connector, self.with_audio.get_active()):
            self.record_setup.set_visible(False)

    def _sync_recorder(self, *_):
        if self.recorder is None:
            return
        running = self.recorder.running
        stopping = self.recorder.stopping
        if running:
            self.record_setup.set_visible(False)
        self.record_button.set_sensitive(not stopping)
        self.record_button.set_tooltip_text(
            self.recorder.message or "Record the selected monitor as MP4")
        self.record_icon.set_label("stop" if running else "videocam")
        self.record_text.set_label(
            "Saving" if stopping else "Stop" if running else "Record")
        if running:
            self.record_button.add_css_class("record-button--active")
        else:
            self.record_button.remove_css_class("record-button--active")
        message = self.recorder.message
        show_status = stopping or bool(message and not running)
        self.record_status.set_visible(show_status)
        if show_status:
            self.record_status.set_label(
                "Saving recording" if stopping else
                "Saved to Videos/Recordings" if message.startswith("Saved to ")
                else message)

    # -- media player section ---------------------------------------------

    def _build_player(self):
        self.player_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        art_frame = Gtk.Box()
        art_frame.add_css_class("art-frame")
        art_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.art = Gtk.Picture()
        self.art.set_size_request(80, 80)
        self.art.set_content_fit(Gtk.ContentFit.COVER)
        art_frame.append(self.art)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        meta.set_valign(Gtk.Align.CENTER)
        meta.set_hexpand(True)
        self.title = _label("track-title", 24)
        self.artist = _label("track-artist", 30)
        self.album = _label("track-album", 34)
        for w in (self.title, self.artist, self.album):
            meta.append(w)

        head.append(art_frame)
        head.append(meta)

        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.time_now = Gtk.Label(label="0:00")
        self.time_now.add_css_class("seek-time")
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.add_css_class("seek")
        self.seek.set_hexpand(True)
        self.seek.set_draw_value(False)
        self.time_total = Gtk.Label(label="0:00")
        self.time_total.add_css_class("seek-time")
        seek_box.append(self.time_now)
        seek_box.append(self.seek)
        seek_box.append(self.time_total)

        drag = Gtk.GestureClick()
        drag.connect("pressed", lambda *_: setattr(self, "_seek_dragging", True))
        drag.connect("released", self._on_seek_released)
        self.seek.add_controller(drag)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        controls.set_halign(Gtk.Align.CENTER)
        self.btn_prev = _media_btn("media-skip-backward-symbolic")
        self.btn_play = _media_btn("media-playback-start-symbolic", main=True)
        self.btn_next = _media_btn("media-skip-forward-symbolic")
        self.btn_prev.connect("clicked", lambda *_: self.media.previous())
        self.btn_play.connect("clicked", lambda *_: self.media.play_pause())
        self.btn_next.connect("clicked", lambda *_: self.media.next())
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            controls.append(b)

        self.player_box.append(head)
        self.player_box.append(seek_box)
        self.player_box.append(controls)
        self.append(self.player_box)

        # idle header shown when nothing plays
        self.idle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.idle_box.set_halign(Gtk.Align.CENTER)
        self.big_clock = Gtk.Label()
        self.big_clock.add_css_class("track-title")
        self.big_date = Gtk.Label()
        self.big_date.add_css_class("track-artist")
        self.idle_box.append(self.big_clock)
        self.idle_box.append(self.big_date)
        self.append(self.idle_box)

    # -- quick toggles ------------------------------------------------------

    def _build_toggles(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_halign(Gtk.Align.CENTER)
        specs = (
            ("wifi", "wifi", "Wi-Fi",
             "nm-connection-editor"),
            ("bluetooth", "bluetooth", "Bluetooth",
             "blueman-manager"),
            ("sound", "volume_up", "Sound", "pavucontrol"),
            ("mic", "mic", "Mic",
             "pavucontrol"),
        )
        for name, icon, label, settings_app in specs:
            button = _control_tile(icon, label)
            button.set_tooltip_text(f"Toggle {label}; right click for settings")
            self.control_buttons[name] = button
            self.control_handlers[name] = button.connect(
                "toggled", self._on_control_toggle, name)
            right = Gtk.GestureClick(button=3)
            right.connect("released", lambda *_args, app=settings_app:
                          Gio.Subprocess.new([app], Gio.SubprocessFlags.NONE))
            button.add_controller(right)
            row.append(button)
        self.append(row)

    def _on_control_toggle(self, button: Gtk.ToggleButton, name: str):
        self._control_busy.add(name)
        button.set_sensitive(False)
        self.controls.set(name, button.get_active(),
                          lambda ok: self._on_control_set(name, ok))

    def _on_control_set(self, name: str, ok: bool):
        self._control_busy.discard(name)
        if not ok:
            self.control_buttons[name].set_tooltip_text(
                f"Could not change {name}; check system permissions")
        self._refresh_control(name)

    def _refresh_control(self, name: str):
        if name in self._control_busy:
            return
        self.controls.read(name, lambda state: self._show_control_state(name, state))

    def _show_control_state(self, name: str, state: bool | None):
        if name in self._control_busy:
            return
        button = self.control_buttons[name]
        button.set_sensitive(state is not None)
        if state is None:
            button.set_tooltip_text(f"{name.capitalize()} unavailable")
            return
        button.handler_block(self.control_handlers[name])
        button.set_active(state)
        button.handler_unblock(self.control_handlers[name])
        button.set_tooltip_text(
            f"{name.capitalize()} {'on' if state else 'off'}; right click for settings")

    def _refresh_controls(self) -> bool:
        if not self.get_mapped():
            return False
        for name in self.control_buttons:
            self._refresh_control(name)
        return True

    # -- tiles -------------------------------------------------------------

    def _build_tiles(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.set_homogeneous(True)

        # battery
        self.battery_tile = _tile()
        self.batt_value = Gtk.Label(label="—")
        self.batt_value.add_css_class("tile-big")
        self.batt_label = Gtk.Label(label="Battery")
        self.batt_label.add_css_class("tile-sub")
        self.battery_tile.append(self.batt_value)
        self.battery_tile.append(self.batt_label)

        # volume
        vol_tile = _tile()
        vol_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        vol_icon.set_halign(Gtk.Align.CENTER)
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.add_css_class("vol")
        self.vol.set_draw_value(False)
        self.vol.connect("change-value", self._on_vol_set)
        vol_label = Gtk.Label(label="Volume")
        vol_label.add_css_class("tile-sub")
        vol_tile.append(vol_icon)
        vol_tile.append(self.vol)
        vol_tile.append(vol_label)

        # pomodoro timer
        self.timer_tile = _tile()
        self.timer_label = Gtk.Label(label="25:00")
        self.timer_label.add_css_class("tile-big")
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btns.set_halign(Gtk.Align.CENTER)
        self.timer_toggle = Gtk.Button()
        self.timer_toggle.add_css_class("tile-btn")
        self.timer_toggle.set_icon_name("media-playback-start-symbolic")
        self.timer_toggle.connect("clicked", self._on_timer_toggle)
        timer_reset = Gtk.Button()
        timer_reset.add_css_class("tile-btn")
        timer_reset.set_icon_name("view-refresh-symbolic")
        timer_reset.connect("clicked", self._on_timer_reset)
        btns.append(self.timer_toggle)
        btns.append(timer_reset)
        self.timer_tile.append(self.timer_label)
        self.timer_tile.append(btns)

        # weather
        self.weather_tile = _tile()
        self.weather_icon = Gtk.Image.new_from_icon_name("weather-clear-symbolic")
        self.weather_icon.set_pixel_size(22)
        self.weather_icon.set_halign(Gtk.Align.CENTER)
        self.weather_temp = Gtk.Label(label="—")
        self.weather_temp.add_css_class("tile-big")
        self.weather_desc = Gtk.Label(label="Weather")
        self.weather_desc.add_css_class("tile-sub")
        self.weather_desc.set_ellipsize(Pango.EllipsizeMode.END)
        self.weather_desc.set_max_width_chars(11)
        self.weather_tile.append(self.weather_icon)
        self.weather_tile.append(self.weather_temp)
        self.weather_tile.append(self.weather_desc)

        for t in (self.battery_tile, vol_tile, self.timer_tile,
                  self.weather_tile):
            row.append(t)
        self.append(row)

        if self.weather is None:
            self.weather_tile.set_visible(False)
        elif self.weather is not None:
            self.weather.connect("changed", self._on_weather)

        # timer state
        self.timer_left = POMODORO
        self.timer_running = False
        self._timer_src = 0

    def _build_footer(self):
        self.sys_label = Gtk.Label()
        self.sys_label.add_css_class("sys-stats")
        self.sys_label.set_visible(self.system is not None)
        if self.system is not None:
            self.system.connect("changed", self._on_system)
        self.append(self.sys_label)

    # -- refresh from services --------------------------------------------

    def refresh_media(self):
        p = self.media.active
        has = p is not None
        self.player_box.set_visible(has)
        self.idle_box.set_visible(not has)
        if not has:
            self._refresh_big_clock()
            self._sync_pos_timer()
            return
        self.title.set_label(p.title or "Unknown track")
        self.artist.set_label(p.artist or "")
        self.album.set_label(p.album or "")
        self.artist.set_visible(bool(p.artist))
        self.album.set_visible(bool(p.album))
        if p.art_path:
            try:
                # load at display size so the picture's natural size is 92px
                # and never inflates the card
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    p.art_path, 80, 80, False)
                self.art.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
            except GLib.Error:
                self.art.set_paintable(None)
        else:
            self.art.set_paintable(None)
        playing = p.status == "Playing"
        self.btn_play.set_icon_name(
            "media-playback-pause-symbolic" if playing
            else "media-playback-start-symbolic")
        self.btn_prev.set_sensitive(p.can_prev)
        self.btn_next.set_sensitive(p.can_next)
        total = p.length_us
        self.seek.set_range(0, max(1, total))
        self.time_total.set_label(_fmt_us(total))
        self._sync_pos_timer()
        self._poll_position()

    def refresh_battery(self):
        if not self.power.available:
            self.battery_tile.set_visible(False)
            return
        self.batt_value.set_label(f"{self.power.percentage:.0f}%")
        self.batt_label.set_label("Charging" if self.power.charging else "Battery")

    def refresh_volume(self, percent: int, muted: bool = False):
        self.vol.set_value(percent)
        if "sound" in self.control_buttons:
            self._show_control_state("sound", not muted)

    def refresh_network(self, name: str, kind: str, connected: bool):
        if not connected:
            _set_chip(self.net_chip, "network-offline-symbolic", "Offline")
        else:
            icon = ("network-wireless-symbolic" if "wireless" in kind
                    else "network-wired-symbolic")
            _set_chip(self.net_chip, icon, name or "Connected")

    def refresh_bluetooth(self, device: str, connected: bool, battery: int):
        self.bt_chip.set_visible(connected)
        if connected:
            text = device if battery < 0 else f"{device} · {battery}%"
            _set_chip(self.bt_chip,
                      pick_icon(self, "bluetooth-symbolic",
                                "network-bluetooth-symbolic",
                                "bluetooth-active-symbolic"), text)

    def _on_weather(self, _svc, temp, desc, icon):
        self.weather_temp.set_label(temp)
        self.weather_desc.set_label(desc)
        # prefer the full-color weather set; symbolic suns get too abstract
        self.weather_icon.set_from_icon_name(pick_icon(
            self, icon.replace("-symbolic", ""), icon,
            "weather-few-clouds"))

    def _on_system(self, _svc, cpu, ram, ram_gib):
        self.sys_label.set_label(
            f"CPU {cpu}%   ·   RAM {ram_gib:.1f} GiB ({ram}%)")

    # -- lifecycle ----------------------------------------------------------

    def _on_map(self):
        self.refresh_media()
        self.refresh_battery()
        self._refresh_big_clock()
        if self.control_buttons:
            self._refresh_controls()
            self._controls_timer = GLib.timeout_add_seconds(
                5, self._refresh_controls)
        if self.weather is not None:
            self.weather.request()
        if self.system is not None:
            self.system.start()

    def _on_unmap(self):
        if self._controls_timer:
            GLib.source_remove(self._controls_timer)
            self._controls_timer = 0
        if self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0
        if self.system is not None:
            self.system.stop()

    # -- seek bar ----------------------------------------------------------

    def _sync_pos_timer(self):
        playing = self.media.active and self.media.active.status == "Playing"
        want = bool(playing) and self.get_mapped()
        if want and not self._pos_timer:
            self._pos_timer = GLib.timeout_add_seconds(1, self._poll_position)
        elif not want and self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0

    def _poll_position(self):
        self.media.get_position(self._on_position)
        return True

    def _on_position(self, pos_us: int):
        self._position_us = pos_us
        if not self._seek_dragging:
            self.seek.set_value(pos_us)
        self.time_now.set_label(_fmt_us(pos_us))

    def _on_seek_released(self, gesture, n, x, y):
        self._seek_dragging = False
        self.media.seek_to(int(self.seek.get_value()))

    def _on_vol_set(self, scale, scroll, value):
        Gio.Subprocess.new(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@",
             f"{int(max(0, min(100, value)))}%"],
            Gio.SubprocessFlags.NONE)
        return False

    # -- pomodoro ----------------------------------------------------------

    def _on_timer_toggle(self, *_):
        self.timer_running = not self.timer_running
        if self.timer_running and not self._timer_src:
            self._timer_src = GLib.timeout_add_seconds(1, self._timer_tick)
        self._sync_timer_ui()

    def _on_timer_reset(self, *_):
        self.timer_running = False
        self.timer_left = POMODORO
        if self._timer_src:
            GLib.source_remove(self._timer_src)
            self._timer_src = 0
        self._sync_timer_ui()

    def _timer_tick(self):
        if not self.timer_running:
            self._timer_src = 0
            return False
        self.timer_left -= 1
        if self.timer_left <= 0:
            self.timer_left = 0
            self.timer_running = False
            self._timer_src = 0
            self._notify_done()
            self._sync_timer_ui()
            return False
        self._sync_timer_ui()
        return True

    def _sync_timer_ui(self):
        m, s = divmod(self.timer_left, 60)
        text = f"{m:02d}:{s:02d}"
        self.timer_label.set_label(text)
        self.timer_toggle.set_icon_name(
            "media-playback-pause-symbolic" if self.timer_running
            else "media-playback-start-symbolic")
        if self.timer_running:
            self.timer_tile.add_css_class("tile--timer-running")
        else:
            self.timer_tile.remove_css_class("tile--timer-running")
        if self.on_timer_change:
            self.on_timer_change(text if self.timer_running else None)

    def _notify_done(self):
        app = Gio.Application.get_default()
        if app:
            note = Gio.Notification.new("Focus round complete")
            note.set_body("25 minutes are up — take a break.")
            app.send_notification("pomodoro", note)

    def _refresh_big_clock(self):
        now = time.localtime()
        if self.cfg.get("clock_24h", True):
            clock = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        else:
            clock = (f"{now.tm_hour % 12 or 12:02d}:{now.tm_min:02d} "
                     f"{'AM' if now.tm_hour < 12 else 'PM'}")
        self.big_clock.set_label(clock)
        self.big_date.set_label(f"{now.tm_mday:02d}.{now.tm_mon:02d}.{now.tm_year}")


def _label(css: str, width: int) -> Gtk.Label:
    lbl = Gtk.Label(xalign=0)
    lbl.add_css_class(css)
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_max_width_chars(width)
    return lbl


def _media_btn(icon: str, main: bool = False) -> Gtk.Button:
    btn = Gtk.Button()
    btn.set_icon_name(icon)
    btn.add_css_class("media-btn")
    if main:
        btn.add_css_class("media-btn--main")
    return btn


def _control_tile(icon: str, label: str) -> Gtk.ToggleButton:
    button = Gtk.ToggleButton()
    button.add_css_class("control-tile")
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    content.set_halign(Gtk.Align.CENTER)
    content.append(_symbol(icon))
    text = Gtk.Label(label=label)
    text.add_css_class("control-label")
    content.append(text)
    button.set_child(content)
    return button


def _symbol(name: str) -> Gtk.Label:
    icon = Gtk.Label(label=name)
    icon.add_css_class("symbol-icon")
    return icon


def _chip(icon: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    box.add_css_class("chip")
    img = Gtk.Image.new_from_icon_name(icon)
    img.set_pixel_size(15)
    box.append(img)
    return box


def _set_chip(chip: Gtk.Box, icon: str, text: str):
    img = chip.get_first_child()
    img.set_from_icon_name(icon)
    chip.set_tooltip_text(text)


def _tile() -> Gtk.Box:
    tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    tile.add_css_class("tile")
    tile.set_valign(Gtk.Align.CENTER)
    return tile


def _fmt_us(us: int) -> str:
    s = max(0, us // 1_000_000)
    return f"{s // 60}:{s % 60:02d}"
