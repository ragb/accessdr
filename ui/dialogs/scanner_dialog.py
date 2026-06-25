"""
ui/dialogs/scanner_dialog.py — Band / channel-map scanner dialog.

Scans either a **band** (a bounded VFO preset's frequency range, using the
band's own step) or a **channel map** (the discrete memory channels of a map).
A free / unbounded band has no defined range, so it cannot be scanned.

Found signals are spoken and listed as they arrive, with playback controls
(Hold, Skip, Stop).
"""

from __future__ import annotations

from typing import Callable, List, Optional

import wx
from accessibility import speech
from config.channels import ChannelMapStore
from config.scenes import SceneStore
from core.scanner import Scanner, ScanResult
from ui.formatting import fmt_freq

# Fallback step when a band defines no step of its own.
_DEFAULT_STEP_HZ = 100_000

_SRC_BAND = 0
_SRC_MAP = 1


class ScannerDialog(wx.Frame):
    """Modeless scanner control and results frame."""

    def __init__(
        self,
        parent: wx.Window,
        scanner: Scanner,
        scenes: SceneStore,
        channels: ChannelMapStore,
        set_mode_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("Scanner"),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("Scanner dialog")
        self._scanner = scanner
        self._scanner.on_signal_found = self._on_signal_found
        self._scanner.on_scan_complete = self._on_scan_complete
        self._set_mode = set_mode_cb or (lambda _m: None)

        # Bands eligible for scanning are the bounded ones (a free band has no
        # range).  Keep the Scene objects parallel to the choice entries.
        self._bands = [s for s in scenes.get_all() if not s.unbounded]
        self._maps = list(channels.maps)

        self._build_ui()
        self.SetSize(540, 580)
        self.Centre()
        speech.output(_("Scanner dialog opened."))

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Source selection ---
        src_box = wx.StaticBox(panel, label=_("Scan Source"))
        src_sizer = wx.StaticBoxSizer(src_box, wx.VERTICAL)

        self._source = wx.RadioBox(
            panel,
            label=_("Scan"),
            choices=[_("Band"), _("Channel map")],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
            name="Scan source",
        )
        self._source.Bind(wx.EVT_RADIOBOX, self._on_source_change)
        src_sizer.Add(self._source, 0, wx.EXPAND | wx.ALL, 4)

        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)

        # Band picker (label before control for screen readers)
        grid.Add(wx.StaticText(panel, label=_("Band:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._band_choice = wx.Choice(
            panel, choices=[s.name for s in self._bands], name="Band to scan"
        )
        if self._bands:
            self._band_choice.SetSelection(0)
        self._band_choice.Bind(wx.EVT_CHOICE, self._on_band_change)
        grid.Add(self._band_choice, 1, wx.EXPAND)

        # Optional min/max frequency override
        grid.Add(wx.StaticText(panel, label=_("Min freq (MHz):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._min_freq = wx.SpinCtrlDouble(
            panel, min=0, max=2000, inc=0.1, name="Minimum frequency",
        )
        self._min_freq.SetDigits(3)
        grid.Add(self._min_freq, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label=_("Max freq (MHz):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._max_freq = wx.SpinCtrlDouble(
            panel, min=0, max=2000, inc=0.1, name="Maximum frequency",
        )
        self._max_freq.SetDigits(3)
        grid.Add(self._max_freq, 1, wx.EXPAND)

        self._populate_freq_limits()

        # Channel-map picker
        grid.Add(wx.StaticText(panel, label=_("Channel map:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._map_choice = wx.Choice(
            panel, choices=[m.name for m in self._maps], name="Channel map to scan"
        )
        if self._maps:
            self._map_choice.SetSelection(0)
        self._map_choice.Bind(wx.EVT_CHOICE, lambda e: self._update_info())
        grid.Add(self._map_choice, 1, wx.EXPAND)

        src_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        self._info = wx.StaticText(panel, label="", name="Scan range")
        src_sizer.Add(self._info, 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(src_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Controls ---
        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self._start_btn = wx.Button(panel, label=_("Start Scan"), name="Start scan")
        self._hold_btn = wx.Button(panel, label=_("Hold (H)"), name="Hold on frequency")
        self._skip_btn = wx.Button(panel, label=_("Skip (K)"), name="Skip frequency")
        self._stop_btn = wx.Button(panel, label=_("Stop (Esc)"), name="Stop scan")
        for btn in (self._start_btn, self._hold_btn, self._skip_btn, self._stop_btn):
            ctrl_row.Add(btn, 0, wx.RIGHT, 6)
        sizer.Add(ctrl_row, 0, wx.ALL, 8)

        # --- Results ---
        res_box = wx.StaticBox(panel, label=_("Results"))
        res_sizer = wx.StaticBoxSizer(res_box, wx.VERTICAL)
        self._results_list = wx.ListCtrl(
            panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Scan results list",
        )
        self._results_list.InsertColumn(0, _("Frequency"), width=150)
        self._results_list.InsertColumn(1, _("Channel"), width=190)
        self._results_list.InsertColumn(2, _("Strength (dBm)"), width=130)
        res_sizer.Add(self._results_list, 1, wx.EXPAND | wx.ALL, 4)

        clear_btn = wx.Button(panel, label=_("Clear Results"), name="Clear scan results")
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        res_sizer.Add(clear_btn, 0, wx.ALL, 4)
        sizer.Add(res_sizer, 1, wx.EXPAND | wx.ALL, 8)

        # Status
        self._status = wx.StaticText(panel, label=_("Idle"), name="Scanner status")
        sizer.Add(self._status, 0, wx.ALL, 8)

        panel.SetSizer(sizer)

        # Bindings
        self._start_btn.Bind(wx.EVT_BUTTON, self._on_start)
        self._hold_btn.Bind(wx.EVT_BUTTON, lambda e: self._scanner.hold())
        self._skip_btn.Bind(wx.EVT_BUTTON, lambda e: self._scanner.skip())
        self._stop_btn.Bind(wx.EVT_BUTTON, self._on_stop)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        # Default source: channel map only if there are no scannable bands.
        self._source.SetSelection(_SRC_BAND if self._bands else _SRC_MAP)
        self._sync_enabled()
        self._update_info()

    # ------------------------------------------------------------------

    def _on_source_change(self, _event: wx.CommandEvent) -> None:
        self._sync_enabled()
        self._update_info()

    def _on_band_change(self, _event: wx.CommandEvent) -> None:
        self._populate_freq_limits()
        self._update_info()

    def _populate_freq_limits(self) -> None:
        band = self._selected_band()
        if band is None:
            return
        self._min_freq.SetRange(band.freq_start / 1e6, band.freq_end / 1e6)
        self._max_freq.SetRange(band.freq_start / 1e6, band.freq_end / 1e6)
        self._min_freq.SetValue(band.freq_start / 1e6)
        self._max_freq.SetValue(band.freq_end / 1e6)

    def _sync_enabled(self) -> None:
        is_band = self._source.GetSelection() == _SRC_BAND
        self._band_choice.Enable(is_band)
        self._min_freq.Enable(is_band)
        self._max_freq.Enable(is_band)
        self._map_choice.Enable(not is_band)

    def _selected_band(self):
        idx = self._band_choice.GetSelection()
        if 0 <= idx < len(self._bands):
            return self._bands[idx]
        return None

    def _selected_map(self):
        idx = self._map_choice.GetSelection()
        if 0 <= idx < len(self._maps):
            return self._maps[idx]
        return None

    def _scan_range(self):
        """Return (start_hz, end_hz) from the freq controls."""
        return int(self._min_freq.GetValue() * 1e6), int(self._max_freq.GetValue() * 1e6)

    def _update_info(self) -> None:
        if self._source.GetSelection() == _SRC_BAND:
            band = self._selected_band()
            if band is None:
                self._info.SetLabel(_("No scannable bands. Define a bounded band first."))
                return
            step = band.step if band.step > 0 else _DEFAULT_STEP_HZ
            start_hz, end_hz = self._scan_range()
            self._info.SetLabel(
                _("{start} to {stop}, step {step} kHz, {mode}").format(
                    start=fmt_freq(start_hz),
                    stop=fmt_freq(end_hz),
                    step=step // 1000,
                    mode=band.mode,
                )
            )
        else:
            cmap = self._selected_map()
            if cmap is None:
                self._info.SetLabel(_("No channel maps."))
                return
            count = len(cmap.sorted_channels())
            self._info.SetLabel(
                ngettext(
                    "{count} channel.", "{count} channels.", count
                ).format(count=count)
            )

    # ------------------------------------------------------------------

    def _on_start(self, _event: wx.CommandEvent) -> None:
        self._results_list.DeleteAllItems()

        if self._source.GetSelection() == _SRC_BAND:
            band = self._selected_band()
            if band is None:
                speech.output(_("No band selected."))
                return
            step = band.step if band.step > 0 else _DEFAULT_STEP_HZ
            start_hz, end_hz = self._scan_range()
            if start_hz >= end_hz:
                speech.output(_("Min frequency must be less than max."))
                return
            self._set_mode(band.mode)
            self._status.SetLabel(_("Scanning band {name}…").format(name=band.name))
            self._scanner.start(start_hz, end_hz, step)
            speech.output(
                _("Scanning band {name}, {start} to {stop}.").format(
                    name=band.name,
                    start=fmt_freq(start_hz),
                    stop=fmt_freq(end_hz),
                )
            )
        else:
            cmap = self._selected_map()
            if cmap is None:
                speech.output(_("No channel map selected."))
                return
            chans = cmap.sorted_channels()
            if not chans:
                speech.output(_("This channel map is empty."))
                return
            self._set_mode(chans[0].mode)
            freqs = [c.frequency for c in chans]
            labels = [
                _("CH{n} {label}").format(n=c.number, label=c.label).strip()
                for c in chans
            ]
            self._status.SetLabel(_("Scanning map {name}…").format(name=cmap.name))
            self._scanner.start_list(freqs, labels)
            speech.output(
                _("Scanning channel map {name}, {count} channels.").format(
                    name=cmap.name, count=len(chans)
                )
            )

    def _on_stop(self, _event: wx.CommandEvent) -> None:
        self._scanner.stop()
        self._status.SetLabel(_("Stopped."))
        speech.output(_("Scan stopped."))

    def _on_clear(self, _event: wx.CommandEvent) -> None:
        self._results_list.DeleteAllItems()

    def _on_signal_found(self, result: ScanResult) -> None:
        """Called (via wx.CallAfter) when scanner finds a signal."""
        idx = self._results_list.InsertItem(
            self._results_list.GetItemCount(), fmt_freq(result.freq_hz)
        )
        self._results_list.SetItem(idx, 1, result.label)
        self._results_list.SetItem(idx, 2, f"{result.strength_db:.1f}")
        if result.label:
            speech.output(
                _("Signal on {label}, {freq}, {db:.0f} dBm.").format(
                    label=result.label, freq=fmt_freq(result.freq_hz),
                    db=result.strength_db,
                )
            )
        else:
            speech.output(
                _("Signal found at {freq}, {db:.0f} dBm.").format(
                    freq=fmt_freq(result.freq_hz), db=result.strength_db
                )
            )

    def _on_scan_complete(self, results: list) -> None:
        count = len(results)
        self._status.SetLabel(
            ngettext(
                "Complete — {count} signal found.",
                "Complete — {count} signals found.",
                count,
            ).format(count=count)
        )
        speech.output(
            ngettext(
                "Scan complete. {count} signal found.",
                "Scan complete. {count} signals found.",
                count,
            ).format(count=count)
        )

    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self._on_stop(event)
        elif code == ord("H"):
            self._scanner.hold()
        elif code == ord("K"):
            self._scanner.skip()
        else:
            event.Skip()
