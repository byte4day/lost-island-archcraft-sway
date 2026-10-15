"""The expanded card — media player up top, quick toggles and tiles below.

Every timer here lives only while the card is mapped: the 1 Hz seek tick,
the 3 s system sampler, the weather request. Unmapping tears it all down.
"""

from __future__ import annotations

import colorsys
import re
import time
import weakref

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango

from lostisland import config
from lostisland.ui import layout
from lostisland.services import tools
from lostisland.services.clipboard import preview as clipboard_preview
from lostisland.services.controls import SystemControls
from lostisland.services.recorder import system_audio_source
from lostisland.ui.draw import pick_icon
from lostisland.ui.launchers import LauncherRow, logo
from lostisland.ui.tools import circle_button

ART_PX = 60
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
TIMER_STEP = 5
# players whose logo ships with the island; others use the icon theme
APP_LOGOS = {"spotify": "spotify.svg"}
HIGH_CPU, HIGH_RAM = 80, 85


class Expanded(Gtk.Box):
    def __init__(self, cfg: dict, media, power, timer=None,
                 weather=None, system=None, on_settings=None, recorder=None,
                 airplay=None, tools_row=None, clipboard=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        self.add_css_class("expanded")
        self.cfg = cfg
        self.media = media
        self.power = power
        self.weather = weather
        self.system = system
        self.timer = timer
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
        self.control_labels: dict[str, Gtk.Label] = {}
        self.on_clip_copied = None
        self.on_edit_changed = None
        self.editing = False

        self.tools = tools_row
        self.clipboard = clipboard
        self._art_css: Gtk.CssProvider | None = None
        self._build_header()
        self._build_player()
        self._build_controls(cfg.get("modules", {}).get("toggles", True))
        self._build_volume()
        self.launchers = LauncherRow(self._launcher_keys(),
                                     on_remove=self._remove_launcher)
        self.append(self.launchers)
        self._build_tray()
        self._build_tiles()
        self._build_footer()
        if self.timer is not None:
            self.timer.connect("changed", lambda *_: self._sync_timer_ui())
            self._sync_timer_ui()

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
        # Record and AirPlay live in the control grid as circles; this
        # section only builds their state lines and the record setup panel.
        self.record_button = circle_button("videocam",
                                           "Record a display as MP4")
        self.record_icon = self.record_button.get_child()
        self.record_text = Gtk.Label(label="Record")
        self.record_button.connect("clicked", self._on_record_clicked)

        self.airplay_button = circle_button("airplay",
                                            "Start the AirPlay receiver")
        self.airplay_text = Gtk.Label(label="AirPlay")
        self.airplay_button.connect("clicked", self._on_airplay_clicked)

        self.clip_button = circle_button(
            "content_paste", "Clipboard history", toggle=True)
        self.clip_button.connect("toggled", self._on_clip_toggled)

        self._status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=6)
        self.airplay_status = Gtk.Label(xalign=0)
        self.airplay_status.add_css_class("record-status")
        self.airplay_status.set_visible(False)
        self._status_box.append(self.airplay_status)

        self.record_status = Gtk.Label(xalign=0)
        self.record_status.add_css_class("record-status")
        self.record_status.set_visible(False)
        self._status_box.append(self.record_status)

        self.record_setup = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                    spacing=9)
        self.record_setup.add_css_class("record-setup")
        self.record_setup.set_visible(False)
        self._status_box.append(self.record_setup)

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
            "Connect to Lost Island from AirPlay; click to stop"
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
        self.player_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.player_box.add_css_class("player")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        art_frame = self.art_frame = Gtk.Box()
        art_frame.add_css_class("art-frame")
        art_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.art = Gtk.Picture()
        self.art.set_size_request(ART_PX, ART_PX)
        self.art.set_content_fit(Gtk.ContentFit.COVER)
        art_frame.append(self.art)
        # no cover: the player's own logo on a soft tile
        self.art_empty = Gtk.Box()
        self.art_empty.set_size_request(ART_PX, ART_PX)
        self.art_empty.add_css_class("art-empty")
        self.art_empty_logo = Gtk.Box(halign=Gtk.Align.CENTER,
                                      valign=Gtk.Align.CENTER)
        self.art_empty_logo.set_size_request(ART_PX, ART_PX)
        self.art_empty.append(self.art_empty_logo)
        art_frame.append(self.art_empty)
        # the playing app's badge on the cover corner, like macOS Now Playing
        art_frame.set_hexpand(False)
        art_frame.set_halign(Gtk.Align.START)
        art_overlay = Gtk.Overlay()
        art_overlay.set_hexpand(False)
        art_overlay.set_child(art_frame)
        art_overlay.set_valign(Gtk.Align.CENTER)
        self.app_badge = Gtk.Box(halign=Gtk.Align.END, valign=Gtk.Align.END)
        self.app_badge.add_css_class("app-badge")
        self.app_badge.set_can_target(False)
        art_overlay.add_overlay(self.app_badge)
        self._badge_app = None

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        meta.set_valign(Gtk.Align.CENTER)
        meta.set_hexpand(True)
        self.title = _label("track-title", 24)
        self.artist = _label("track-artist", 30)
        self.album = _label("track-album", 34)
        for w in (self.title, self.artist, self.album):
            meta.append(w)

        head.append(art_overlay)
        head.append(meta)

        seek_box = self.seek_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
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

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=34)
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
        self.idle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.idle_box.add_css_class("idle")
        self.big_clock = Gtk.Label(xalign=0)
        self.big_clock.add_css_class("idle-clock")
        self.big_date = Gtk.Label(xalign=0)
        self.big_date.add_css_class("idle-date")
        self.idle_box.append(self.big_clock)
        self.idle_box.append(self.big_date)
        self.append(self.idle_box)

    # -- quick toggles ------------------------------------------------------

    def _build_controls(self, with_toggles: bool):
        """The control platter: round buttons in the user's order. Edit mode
        (pencil in the footer, or a long press) lets you drag them, remove
        them, and add hidden ones back, like Control Center on a Mac."""
        widgets: dict[str, tuple[Gtk.Button, Gtk.Label | str]] = {}
        if with_toggles:
            specs = (
                ("wifi", "nm-connection-editor"),
                ("bluetooth", "blueman-manager"),
                ("sound", "pavucontrol"),
                ("mic", "pavucontrol"),
            )
            for name, settings_app in specs:
                icon, label = layout.CONTROLS[name]
                button = circle_button(
                    icon, f"Turn {label} on or off; right-click for settings",
                    toggle=True)
                self.control_buttons[name] = button
                self.control_handlers[name] = button.connect(
                    "toggled", self._on_control_toggle, name)
                right = Gtk.GestureClick(button=3)
                right.connect("released", lambda *_args, app=settings_app:
                              _spawn([app]))
                button.add_controller(right)
                caption = Gtk.Label(label=label)
                self.control_labels[name] = caption
                widgets[name] = (button, caption)
        if self.tools is not None:
            widgets.update({
                "focus": (self.tools.dnd, "Focus"),
                "power": (self.tools.power, "Power"),
                "screen": (self.tools.shot, "Screen"),
                "area": (self.tools.region, "Area"),
                "color": (self.tools.picker, "Color"),
            })
            lock = circle_button("lock", "Lock the screen")
            lock.connect("clicked", lambda *_: self.tools.lock())
            widgets["lock"] = (lock, "Lock")
        if self.recorder is not None:
            widgets["record"] = (self.record_button, self.record_text)
        if self.airplay is not None:
            widgets["airplay"] = (self.airplay_button, self.airplay_text)
        if self.clipboard is not None and self.clipboard.available:
            widgets["clipboard"] = (self.clip_button, "Clipboard")
        if self.timer is not None:
            timer_btn = circle_button("timer", "Start or pause the focus timer",
                                      toggle=True)
            self._timer_btn_handler = timer_btn.connect(
                "toggled", lambda *_: self.timer.toggle())
            self.timer_caption = Gtk.Label(label="Timer")
            widgets["timer"] = (timer_btn, self.timer_caption)
            self.timer_button = timer_btn
        settings = circle_button("settings", "Island settings")
        settings.connect("clicked",
                         lambda *_: self.on_settings and self.on_settings())
        widgets["settings"] = (settings, "Settings")

        self.available_controls = [k for k in layout.CONTROLS if k in widgets]
        self.cells: dict[str, Gtk.Overlay] = {}
        for key, (button, caption) in widgets.items():
            self.cells[key] = self._edit_cell(key, button, caption)

        self.grid = Gtk.Grid(column_spacing=4, row_spacing=12)
        self.grid.set_column_homogeneous(True)
        self.grid.add_css_class("controls")
        # dropping on empty grid space moves a control to the end
        end_drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        end_drop.connect("drop", lambda _t, value, _x, _y:
                         self._move_control(value, None))
        self.grid.add_controller(end_drop)

        platter = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        platter.add_css_class("platter")
        platter.add_css_class("controls-platter")
        platter.append(self.grid)
        # grid + its slide-out panels share one zero-spacing column, so
        # closed panels do not leave gaps; panels carry their own margin
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        section.append(platter)
        self._section = section
        self._build_clipboard()
        if self.tools is not None:
            section.append(self.tools.power_revealer)
            section.append(self.tools.message)
        self._status_box.add_css_class("status-box")
        section.append(self._status_box)
        self.append(section)
        self._render_grid()

    def _control_keys(self) -> list[str]:
        saved = self.cfg.get("controls", layout.DEFAULT_CONTROLS)
        return layout.normalize(saved, self.available_controls)

    def _launcher_keys(self) -> list[str]:
        saved = self.cfg.get("launchers", layout.DEFAULT_LAUNCHERS)
        return layout.normalize(saved, list(layout.LAUNCHERS))

    def _edit_cell(self, key: str, button: Gtk.Button,
                   caption: Gtk.Label | str) -> Gtk.Overlay:
        cell = Gtk.Overlay()
        cell.set_child(_cell(button, caption))
        cell.set_halign(Gtk.Align.CENTER)
        # in edit mode a shield takes the pointer, so a press drags the
        # control instead of switching it
        shield = Gtk.Box()
        shield.add_css_class("edit-shield")
        shield.set_visible(False)
        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", lambda *_a, k=key:
                       Gdk.ContentProvider.new_for_value(k))
        source.connect("drag-begin", self._on_drag_begin, cell)
        source.connect("drag-end", lambda *_a, c=cell:
                       c.remove_css_class("dragging"))
        shield.add_controller(source)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("enter", lambda *_a, c=cell: (
            c.add_css_class("drop-hover"), Gdk.DragAction.MOVE)[1])
        drop.connect("leave", lambda *_a, c=cell:
                     c.remove_css_class("drop-hover"))
        drop.connect("drop", lambda _t, value, _x, _y, k=key, c=cell: (
            c.remove_css_class("drop-hover"),
            self._move_control(value, k))[1])
        shield.add_controller(drop)
        cell.add_overlay(shield)

        badge = Gtk.Button(label="−")
        badge.add_css_class("edit-badge")
        badge.set_halign(Gtk.Align.START)
        badge.set_valign(Gtk.Align.START)
        badge.set_visible(False)
        badge.set_tooltip_text("Remove from the island")
        badge.connect("clicked", lambda *_a, k=key: self._remove_control(k))
        cell.add_overlay(badge)
        cell.shield, cell.badge = shield, badge

        hold = Gtk.GestureLongPress()
        hold.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        hold.connect("pressed", lambda g, *_a: (
            g.set_state(Gtk.EventSequenceState.CLAIMED),
            self.set_editing(True)) if not self.editing else None)
        cell.add_controller(hold)
        return cell

    def _on_drag_begin(self, source, drag, cell):
        cell.add_css_class("dragging")
        paintable = Gtk.WidgetPaintable.new(cell)
        source.set_icon(paintable, cell.get_width() // 2,
                        cell.get_height() // 2)

    def _render_grid(self):
        while (child := self.grid.get_first_child()) is not None:
            self.grid.remove(child)
        for index, key in enumerate(self._control_keys()):
            self.grid.attach(self.cells[key], index % layout.COLUMNS,
                             index // layout.COLUMNS, 1, 1)
        self._sync_edit_marks()

    def _sync_edit_marks(self):
        for index, key in enumerate(self._control_keys()):
            cell = self.cells[key]
            cell.shield.set_visible(self.editing)
            cell.badge.set_visible(self.editing)
            for cls in ("jiggle-a", "jiggle-b"):
                cell.remove_css_class(cls)
            if self.editing:
                cell.add_css_class("jiggle-a" if index % 2 else "jiggle-b")
        self.launchers.set_editing(self.editing) if hasattr(
            self, "launchers") else None

    def _save_layout(self, controls=None, launchers=None):
        if controls is not None:
            self.cfg["controls"] = controls
        if launchers is not None:
            self.cfg["launchers"] = launchers
        config.save(self.cfg)
        self._render_grid()
        self.launchers.set_keys(self._launcher_keys())
        self._render_tray()

    def _move_control(self, key, before) -> bool:
        if not isinstance(key, str) or key not in self.cells:
            return False
        self._save_layout(controls=layout.move(self._control_keys(), key,
                                               before))
        return True

    def _remove_control(self, key: str):
        self._save_layout(controls=layout.remove(self._control_keys(), key))

    def _add_control(self, key: str):
        self._save_layout(controls=layout.add(self._control_keys(), key))

    def _remove_launcher(self, key: str):
        self._save_layout(launchers=layout.remove(self._launcher_keys(), key))

    def _add_launcher(self, key: str):
        self._save_layout(launchers=layout.add(self._launcher_keys(), key))

    def set_editing(self, editing: bool):
        if editing == self.editing:
            return
        self.editing = editing
        if editing:
            self.clip_button.set_active(False)
            if self.tools is not None:
                self.tools.close_power()
        self._sync_edit_marks()
        self._render_tray()
        self.tray_revealer.set_reveal_child(editing)
        self.edit_button.get_child().set_label("check" if editing else "edit")
        self.edit_button.set_tooltip_text(
            "Done editing" if editing else "Edit controls")
        if self.on_edit_changed:
            self.on_edit_changed(editing)

    # -- edit tray: hidden controls you can add back ---------------------------

    def _build_tray(self):
        self.tray_revealer = Gtk.Revealer()
        self.tray_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.tray_revealer.set_transition_duration(220)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("platter")
        panel.add_css_class("tray")
        hint = Gtk.Label(
            label="Drag to reorder. Tap − to remove, + to add.", xalign=0)
        hint.add_css_class("tray-hint")
        panel.append(hint)
        self.tray_grid = Gtk.Grid(column_spacing=4, row_spacing=10)
        self.tray_grid.set_column_homogeneous(True)
        panel.append(self.tray_grid)
        self.tray_apps = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                 spacing=8)
        panel.append(self.tray_apps)
        self.tray_empty = Gtk.Label(label="Everything is already on the island",
                                    xalign=0)
        self.tray_empty.add_css_class("tray-hint")
        panel.append(self.tray_empty)
        self.tray_revealer.set_child(panel)
        self.append(self.tray_revealer)

    def _render_tray(self):
        for box in (self.tray_grid, self.tray_apps):
            while (child := box.get_first_child()) is not None:
                box.remove(child)
        hidden = layout.hidden(self._control_keys(), self.available_controls)
        for index, key in enumerate(hidden):
            icon, label = layout.CONTROLS[key]
            button = circle_button(icon, f"Add {label}")
            button.add_css_class("circle--ghost")
            button.connect("clicked", lambda *_a, k=key: self._add_control(k))
            cell = Gtk.Overlay()
            cell.set_child(_cell(button, label))
            cell.set_halign(Gtk.Align.CENTER)
            plus = Gtk.Label(label="+")
            plus.add_css_class("add-badge")
            plus.set_halign(Gtk.Align.START)
            plus.set_valign(Gtk.Align.START)
            plus.set_can_target(False)
            cell.add_overlay(plus)
            self.tray_grid.attach(cell, index % layout.COLUMNS,
                                  index // layout.COLUMNS, 1, 1)
        # pad the row so the tray lines up with the grid's six columns
        for index in range(len(hidden), layout.COLUMNS):
            self.tray_grid.attach(Gtk.Box(), index, 0, 1, 1)
        hidden_apps = layout.hidden(self._launcher_keys(), list(layout.LAUNCHERS))
        for key in hidden_apps:
            name, artwork, _cmd = layout.LAUNCHERS[key]
            button = Gtk.Button()
            button.add_css_class("launcher-btn")
            button.add_css_class("launcher-btn--ghost")
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            content.append(Gtk.Label(label="+"))
            content.append(logo(artwork, 16))
            content.append(Gtk.Label(label=name))
            button.set_child(content)
            button.set_tooltip_text(f"Add {name}")
            button.connect("clicked", lambda *_a, k=key: self._add_launcher(k))
            self.tray_apps.append(button)
        self.tray_grid.set_visible(bool(hidden))
        self.tray_apps.set_visible(bool(hidden_apps))
        self.tray_empty.set_visible(not hidden and not hidden_apps)

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

    # -- clipboard ----------------------------------------------------------

    def _build_clipboard(self):
        self.clip_revealer = Gtk.Revealer()
        self.clip_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.clip_revealer.set_transition_duration(180)
        if self.clipboard is None or not self.clipboard.available:
            return
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.add_css_class("clip-panel")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Recently copied", xalign=0, hexpand=True)
        title.add_css_class("clip-title")
        clear = Gtk.Button(label="Clear")
        clear.add_css_class("clip-clear")
        clear.connect("clicked", lambda *_: self.clipboard.clear())
        head.append(title)
        head.append(clear)
        panel.append(head)

        self.clip_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                 spacing=2)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(196)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(self.clip_list)
        panel.append(scroller)
        self.clip_revealer.set_child(panel)
        self._section.append(self.clip_revealer)

        self_ref = weakref.ref(self)

        def on_changed(*_):
            widget = self_ref()
            if widget is not None:
                widget._render_clipboard()

        handler = self.clipboard.connect("changed", on_changed)
        weakref.finalize(self, self.clipboard.disconnect, handler)
        self._render_clipboard()

    def _render_clipboard(self):
        while (child := self.clip_list.get_first_child()) is not None:
            self.clip_list.remove(child)
        if not self.clipboard.history:
            empty = Gtk.Label(label="Copy some text and it shows up here",
                              xalign=0)
            empty.add_css_class("clip-empty")
            self.clip_list.append(empty)
            return
        for text in self.clipboard.history:
            button = Gtk.Button()
            button.add_css_class("clip-item")
            line = Gtk.Label(label=clipboard_preview(text), xalign=0)
            line.set_ellipsize(Pango.EllipsizeMode.END)
            button.set_child(line)
            button.set_tooltip_text("Copy again")
            button.connect("clicked", self._on_clip_pick, text)
            self.clip_list.append(button)

    def _on_clip_toggled(self, button: Gtk.ToggleButton):
        open_ = button.get_active()
        if open_ and self.tools is not None:
            self.tools.close_power()
        self.clip_revealer.set_reveal_child(open_)

    def _on_clip_pick(self, _button: Gtk.Button, text: str):
        self.clipboard.copy(text)
        self.clip_button.set_active(False)
        if self.on_clip_copied:
            self.on_clip_copied(text)

    def _build_volume(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("volume-row")
        self.vol_icon = _symbol("volume_up")
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.add_css_class("vol")
        self.vol.set_hexpand(True)
        self.vol.set_draw_value(False)
        self.vol.connect("change-value", self._on_vol_set)
        self.vol_value = Gtk.Label(label="")
        self.vol_value.add_css_class("vol-value")
        self.vol_value.set_width_chars(4)
        self.vol_value.set_xalign(1)
        row.append(self.vol_icon)
        row.append(self.vol)
        row.append(self.vol_value)
        self.append(row)

    def _build_tiles(self):
        """One quiet line: focus timer, weather, battery, then edit, power
        and settings."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("info-line")

        self.timer_tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=6)
        self.timer_tile.add_css_class("info-item")
        self.timer_tile.append(_symbol("timer"))
        self.timer_label = Gtk.Label(label="25:00")
        self.timer_label.add_css_class("info-value")
        self.timer_tile.set_tooltip_text(
            "Focus timer; scroll to change the length")
        timer_scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE)
        timer_scroll.connect("scroll", self._on_timer_scroll)
        self.timer_tile.add_controller(timer_scroll)
        self.timer_toggle = Gtk.Button()
        self.timer_toggle.add_css_class("mini-btn")
        self.timer_toggle.set_icon_name("media-playback-start-symbolic")
        self.timer_toggle.set_tooltip_text("Start or pause the focus timer")
        self.timer_toggle.connect("clicked", lambda *_: self.timer.toggle())
        timer_reset = Gtk.Button()
        timer_reset.add_css_class("mini-btn")
        timer_reset.set_icon_name("view-refresh-symbolic")
        timer_reset.set_tooltip_text("Reset the focus timer")
        timer_reset.connect("clicked", lambda *_: self.timer.reset())
        self.timer_tile.append(self.timer_label)
        self.timer_tile.append(self.timer_toggle)
        self.timer_tile.append(timer_reset)
        self.timer_tile.set_visible(self.timer is not None)

        self.weather_tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                    spacing=6)
        self.weather_tile.add_css_class("info-item")
        self.weather_tile.set_hexpand(True)
        self.weather_tile.set_halign(Gtk.Align.CENTER)
        self.weather_icon = Gtk.Image.new_from_icon_name("weather-clear-symbolic")
        self.weather_icon.set_pixel_size(18)
        self.weather_temp = Gtk.Label(label="")
        self.weather_temp.add_css_class("info-value")
        self.weather_desc = Gtk.Label(label="")
        self.weather_desc.add_css_class("info-sub")
        self.weather_tile.append(self.weather_icon)
        self.weather_tile.append(self.weather_temp)
        self.weather_tile.append(self.weather_desc)

        self.battery_tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                    spacing=4)
        self.battery_tile.add_css_class("info-item")
        self.batt_icon = _symbol("battery_full")
        self.batt_value = Gtk.Label(label="")
        self.batt_value.add_css_class("info-value")
        self.batt_label = self.batt_value  # kept for older callers
        self.battery_tile.append(self.batt_icon)
        self.battery_tile.append(self.batt_value)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.edit_button = Gtk.Button()
        self.edit_button.add_css_class("mini-btn")
        self.edit_button.set_child(_symbol("edit"))
        self.edit_button.set_tooltip_text("Edit controls")
        self.edit_button.connect(
            "clicked", lambda *_: self.set_editing(not self.editing))
        actions.append(self.edit_button)
        if self.tools is not None:
            power = Gtk.Button()
            power.add_css_class("mini-btn")
            power.set_child(_symbol("power_settings_new"))
            power.set_tooltip_text("Lock, sleep, restart or shut down")
            power.connect("clicked", lambda *_: self.tools.power.set_active(
                not self.tools.power.get_active()))
            actions.append(power)
        settings = Gtk.Button()
        settings.add_css_class("mini-btn")
        settings.set_child(_symbol("settings"))
        settings.set_tooltip_text("Island settings")
        settings.connect("clicked",
                         lambda *_: self.on_settings and self.on_settings())
        actions.append(settings)

        row.append(self.timer_tile)
        row.append(self.weather_tile)
        row.append(self.battery_tile)
        row.append(actions)
        self.append(row)

        if self.weather is None:
            self.weather_tile.set_visible(False)
        else:
            self.weather.connect("changed", self._on_weather)

    def _build_footer(self):
        # CPU and RAM only speak up when something is wrong
        self.sys_label = Gtk.Label()
        self.sys_label.add_css_class("sys-stats")
        self.sys_label.set_visible(False)
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
            self._set_art_tint(None)
            self._refresh_big_clock()
            self._sync_pos_timer()
            return
        self.title.set_label(p.title or "Unknown track")
        self.artist.set_label(p.artist or "")
        self.album.set_label(p.album or "")
        self.artist.set_visible(bool(p.artist))
        self.album.set_visible(bool(p.album))
        pixbuf = None
        if p.art_path:
            try:
                # load at display size so the picture never inflates the card
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    p.art_path, ART_PX, ART_PX, False)
            except GLib.Error:
                pixbuf = None
        self.art.set_paintable(
            Gdk.Texture.new_for_pixbuf(pixbuf) if pixbuf else None)
        self.art.set_visible(pixbuf is not None)
        self.art_empty.set_visible(pixbuf is None)
        self._set_app_badge(getattr(p, "app", ""))
        # with no cover the tile already shows the app's logo
        self.app_badge.set_visible(pixbuf is not None
                                   and self.app_badge.get_first_child() is not None)
        self._set_art_tint(art_tint(pixbuf) if pixbuf else None)
        playing = p.status == "Playing"
        self.btn_play.set_icon_name(
            "media-playback-pause-symbolic" if playing
            else "media-playback-start-symbolic")
        self.btn_prev.set_sensitive(p.can_prev)
        self.btn_next.set_sensitive(p.can_next)
        total = p.length_us
        # browsers often publish no track length; a bar pinned at the end
        # with "0:00" is worse than no bar
        self.seek_box.set_visible(total > 0)
        self.seek.set_range(0, max(1, total))
        self.time_total.set_label(_fmt_us(total))
        self._sync_pos_timer()
        self._poll_position()

    def _app_logo(self, app: str, size: int) -> Gtk.Widget | None:
        if app in APP_LOGOS:
            return logo(APP_LOGOS[app], size)
        theme = Gtk.IconTheme.get_for_display(
            self.get_display() or Gdk.Display.get_default())
        for name in (app, f"{app}-browser", f"org.mozilla.{app}",
                     f"com.{app}.Client", f"org.chromium.{app}"):
            if name and theme.has_icon(name):
                image = Gtk.Image.new_from_icon_name(name)
                image.set_pixel_size(size)
                return image
        return None

    def _set_app_badge(self, app: str):
        if app == self._badge_app:
            return
        self._badge_app = app
        for box in (self.app_badge, self.art_empty_logo):
            while (child := box.get_first_child()) is not None:
                box.remove(child)
        badge = self._app_logo(app, 18)
        self.app_badge.set_visible(badge is not None)
        if badge is not None:
            self.app_badge.append(badge)
        big = self._app_logo(app, 30)
        if big is None:
            big = _symbol("music_note")
            big.add_css_class("art-empty-symbol")
        for setter in (big.set_hexpand, big.set_vexpand):
            setter(True)
        big.set_halign(Gtk.Align.CENTER)
        big.set_valign(Gtk.Align.CENTER)
        self.art_empty_logo.append(big)

    def _set_art_tint(self, rgb: tuple[int, int, int] | None):
        display = self.get_display() or Gdk.Display.get_default()
        if self._art_css is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._art_css)
            self._art_css = None
        if rgb is None:
            return
        base, bright = rgb, _shade(rgb, value=0.95, min_sat=0.25)
        provider = Gtk.CssProvider()
        provider.load_from_string(f"""
            .player {{
              background-image: linear-gradient(160deg,
                  rgba({base[0]}, {base[1]}, {base[2]}, 0.62),
                  rgba({base[0]}, {base[1]}, {base[2]}, 0.18));
              border-color: rgba({bright[0]}, {bright[1]}, {bright[2]}, 0.22);
            }}
            .player scale.seek highlight {{
              background: rgb({bright[0]}, {bright[1]}, {bright[2]});
            }}
        """)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._art_css = provider

    def refresh_battery(self):
        if not self.power.available:
            self.battery_tile.set_visible(False)
            return
        pct = self.power.percentage
        self.batt_value.set_label(f"{pct:.0f}%")
        self.batt_icon.set_label(
            "battery_charging_full" if self.power.charging else
            "battery_full" if pct > 80 else "battery_5_bar" if pct > 55 else
            "battery_3_bar" if pct > 30 else "battery_1_bar")
        self.battery_tile.set_tooltip_text(
            "Charging" if self.power.charging else "On battery")

    def refresh_volume(self, percent: int, muted: bool = False):
        self.vol.set_value(percent)
        self.vol_value.set_label("Muted" if muted else f"{percent}%")
        self.vol_icon.set_label(
            "volume_off" if muted or percent == 0 else
            "volume_down" if percent < 50 else "volume_up")
        if "sound" in self.control_buttons:
            self._show_control_state("sound", not muted)

    def _read_volume(self):
        def got_volume(ok: bool, out: str):
            match = re.search(r"(\d+)%", out) if ok else None
            if match:
                percent = int(match.group(1))
                tools.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                          lambda ok2, out2: self.refresh_volume(
                              percent, ok2 and "yes" in out2))
        tools.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], got_volume)

    def refresh_network(self, name: str, kind: str, connected: bool):
        label = self.control_labels.get("wifi")
        if label is None:
            return
        wireless = connected and "wireless" in kind
        label.set_label(_short(name) if wireless and name else "Wi-Fi")
        self.control_buttons["wifi"].get_parent().set_tooltip_text(
            f"Connected to {name}" if connected and name else
            "Offline" if not connected else "Connected")

    def refresh_bluetooth(self, device: str, connected: bool, battery: int):
        label = self.control_labels.get("bluetooth")
        if label is None:
            return
        label.set_label(_short(device) if connected and device else "Bluetooth")
        if connected:
            self.control_buttons["bluetooth"].get_parent().set_tooltip_text(
                device if battery < 0 else f"{device}, {battery}% battery")

    def _on_weather(self, _svc, temp, desc, icon):
        self.weather_temp.set_label(temp)
        # the short word ("Storm") fits; the full text goes in the tooltip
        self.weather_desc.set_label(getattr(self.weather, "short", "") or desc)
        self.weather_tile.set_tooltip_text(desc)
        # prefer the full-color weather set; symbolic suns get too abstract
        self.weather_icon.set_from_icon_name(pick_icon(
            self, icon.replace("-symbolic", ""), icon,
            "weather-few-clouds"))

    def _on_system(self, _svc, cpu, ram, ram_gib):
        busy = cpu >= HIGH_CPU or ram >= HIGH_RAM
        self.sys_label.set_visible(busy)
        if busy:
            self.sys_label.set_label(
                f"CPU busy: {cpu}%" if cpu >= HIGH_CPU
                else f"Memory almost full: {ram_gib:.1f} GiB ({ram}%)")

    # -- lifecycle ----------------------------------------------------------

    def _on_map(self):
        self.refresh_media()
        self.refresh_battery()
        self._read_volume()
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
        self.set_editing(False)
        self.clip_button.set_active(False)
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

    # -- focus timer (shared service) ---------------------------------------

    def _on_timer_scroll(self, _ctrl, _dx, dy):
        if self.timer is None:
            return False
        step = -TIMER_STEP if dy > 0 else TIMER_STEP
        if self.timer.set_minutes(self.timer.minutes + step):
            self.cfg["timer_minutes"] = self.timer.minutes
            config.save(self.cfg)
        return True

    def _sync_timer_ui(self):
        t = self.timer
        if t is None:
            return
        self.timer_label.set_label(t.text)
        self.timer_toggle.set_icon_name(
            "media-playback-pause-symbolic" if t.running
            else "media-playback-start-symbolic")
        if t.running:
            self.timer_tile.add_css_class("info-item--running")
        else:
            self.timer_tile.remove_css_class("info-item--running")
        if hasattr(self, "timer_button"):
            self.timer_button.handler_block(self._timer_btn_handler)
            self.timer_button.set_active(t.running)
            self.timer_button.handler_unblock(self._timer_btn_handler)
            self.timer_caption.set_label(t.text if t.touched else "Timer")

    def _refresh_big_clock(self):
        now = time.localtime()
        if self.cfg.get("clock_24h", True):
            clock = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        else:
            clock = (f"{now.tm_hour % 12 or 12}:{now.tm_min:02d} "
                     f"{'AM' if now.tm_hour < 12 else 'PM'}")
        self.big_clock.set_label(clock)
        # spelled out here so the system locale cannot change the script
        self.big_date.set_label(
            f"{_DAYS[now.tm_wday]}, {now.tm_mday} {_MONTHS[now.tm_mon - 1]}")


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


def _symbol(name: str) -> Gtk.Label:
    icon = Gtk.Label(label=name)
    icon.add_css_class("symbol-icon")
    return icon


def _cell(button: Gtk.Button, caption: Gtk.Label | str) -> Gtk.Box:
    """A circle with its caption underneath, Control Center style."""
    cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    cell.set_halign(Gtk.Align.CENTER)
    button.set_halign(Gtk.Align.CENTER)
    label = caption if isinstance(caption, Gtk.Label) else Gtk.Label(label=caption)
    label.add_css_class("circle-label")
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(10)
    cell.append(button)
    cell.append(label)
    return cell


def _short(text: str, limit: int = 9) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _spawn(argv: list[str]):
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
    except GLib.Error:
        pass


def _shade(rgb, value: float, min_sat: float = 0.0):
    h, sat, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    r, g, b = colorsys.hsv_to_rgb(h, max(min_sat, min(sat, 0.85)), value)
    return int(r * 255), int(g * 255), int(b * 255)


def art_tint(pixbuf: GdkPixbuf.Pixbuf) -> tuple[int, int, int]:
    """Dominant color of the cover, darkened enough for white text."""
    one = pixbuf.scale_simple(1, 1, GdkPixbuf.InterpType.BILINEAR)
    data = one.get_pixels()
    rgb = (data[0], data[1], data[2])
    _h, sat, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return _shade(rgb, value=max(0.30, min(v, 0.55)), min_sat=min(sat, 0.5))


def _fmt_us(us: int) -> str:
    s = max(0, us // 1_000_000)
    h, rest = divmod(s, 3600)
    if h:
        return f"{h}:{rest // 60:02d}:{rest % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"
