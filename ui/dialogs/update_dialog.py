"""
ui/dialogs/update_dialog.py — Accessible "update available" and download dialogs.

Standard wx widgets only (no manual speech) so the screen reader reads them
natively.  ``UpdateDialog`` presents the new release and lets the user choose
Install / Remind me later / Skip this version.  ``download_and_install`` shows
an accessible progress dialog, fetches the installer, launches it, and signals
the caller to exit so the files can be replaced.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading

import wx

from core.updater import UpdateInfo, download_asset

logger = logging.getLogger(__name__)

# UpdateDialog results.
RESULT_INSTALL = wx.ID_OK
RESULT_LATER = wx.ID_CANCEL
RESULT_SKIP = wx.ID_NO


class UpdateDialog(wx.Dialog):
    """Modal 'a new version is available' dialog (fully accessible)."""

    def __init__(self, parent, info: UpdateInfo, current_version: str) -> None:
        super().__init__(
            parent, title=_("Update Available — AccessDR"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("Update Available")
        self._info = info
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        head = wx.StaticText(
            panel,
            label=_("A new version of AccessDR is available."),
        )
        head.SetFont(head.GetFont().Bold())
        sizer.Add(head, 0, wx.ALL, 8)

        sizer.Add(
            wx.StaticText(panel, label=_("Installed version: {v}").format(v=current_version)),
            0, wx.LEFT | wx.RIGHT, 8,
        )
        sizer.Add(
            wx.StaticText(panel, label=_("New version: {v}  ({name})").format(
                v=info.version, name=info.name)),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8,
        )

        # Release notes — label before control (screen-reader association).
        sizer.Add(wx.StaticText(panel, label=_("Release notes:")), 0, wx.LEFT | wx.RIGHT, 8)
        notes = wx.TextCtrl(
            panel, value=info.body or _("(no release notes)"),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
            name="Release notes",
        )
        notes.SetMinSize((460, 220))
        sizer.Add(notes, 1, wx.EXPAND | wx.ALL, 8)

        # Buttons
        row = wx.BoxSizer(wx.HORIZONTAL)
        install_btn = wx.Button(panel, RESULT_INSTALL, _("Download and Install"))
        install_btn.SetDefault()
        later_btn = wx.Button(panel, RESULT_LATER, _("Remind Me Later"))
        skip_btn = wx.Button(panel, RESULT_SKIP, _("Skip This Version"))
        for b in (install_btn, later_btn, skip_btn):
            b.Bind(wx.EVT_BUTTON, self._on_button)
            row.Add(b, 0, wx.LEFT, 6)
        sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(sizer)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(frame_sizer)
        self.SetSize((520, 460))
        self.Centre()

    def _on_button(self, event: wx.CommandEvent) -> None:
        self.EndModal(event.GetId())


class _DownloadDialog(wx.Dialog):
    """Modal accessible download progress dialog with Cancel."""

    def __init__(self, parent, info: UpdateInfo) -> None:
        super().__init__(parent, title=_("Downloading Update"), style=wx.CAPTION)
        self.SetName("Downloading Update")
        self._info = info
        self._cancelled = False
        self.result_path: str | None = None
        self.error: str | None = None

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._status = wx.StaticText(
            panel, label=_("Downloading {name}…").format(name=info.asset_name),
            name="Download status",
        )
        sizer.Add(self._status, 0, wx.ALL, 10)
        self._gauge = wx.Gauge(panel, range=100, size=(360, -1), name="Download progress")
        sizer.Add(self._gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        cancel = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        cancel.Bind(wx.EVT_BUTTON, self._on_cancel)
        sizer.Add(cancel, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.Centre()

    def run(self) -> str | None:
        """Show modally while downloading; return the saved path or None."""
        threading.Thread(target=self._worker, daemon=True, name="Updater").start()
        self.ShowModal()
        return self.result_path

    def _worker(self) -> None:
        try:
            path = download_asset(
                self._info.asset_url,
                progress_cb=self._on_progress,
                cancel_cb=lambda: self._cancelled,
            )
            wx.CallAfter(self._finish, path, None)
        except Exception as exc:   # noqa: BLE001
            logger.error("update download failed: %s", exc)
            wx.CallAfter(self._finish, None, str(exc))

    def _on_progress(self, done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else 0
        wx.CallAfter(self._update_ui, pct, done, total)

    def _update_ui(self, pct: int, done: int, total: int) -> None:
        if total:
            self._gauge.SetValue(pct)
            self._status.SetLabel(_("Downloading… {pct}%").format(pct=pct))
        else:
            self._gauge.Pulse()
            self._status.SetLabel(
                _("Downloading… {kb} KB").format(kb=done // 1024))

    def _finish(self, path: str | None, error: str | None) -> None:
        self.result_path = path
        self.error = error
        self.EndModal(wx.ID_OK if path else wx.ID_CANCEL)

    def _on_cancel(self, _event: wx.CommandEvent) -> None:
        self._cancelled = True
        self._status.SetLabel(_("Cancelling…"))


def download_and_install(parent, info: UpdateInfo) -> bool:
    """Download the installer and launch it.  Returns True if the app should
    exit (installer launched), False otherwise."""
    dlg = _DownloadDialog(parent, info)
    path = dlg.run()
    error = dlg.error
    dlg.Destroy()
    if path is None:
        if error:
            wx.MessageBox(
                _("The update could not be downloaded:\n{err}").format(err=error),
                _("Update Failed"), wx.OK | wx.ICON_ERROR, parent,
            )
        return False
    try:
        # Launch the NSIS installer detached, then the caller exits so it can
        # overwrite the running install.
        subprocess.Popen([path], close_fds=True)
        return True
    except Exception as exc:   # noqa: BLE001
        logger.error("failed to launch installer %s: %s", path, exc)
        wx.MessageBox(
            _("Could not launch the installer:\n{err}\n\nIt was saved to:\n{path}").format(
                err=exc, path=path),
            _("Update Failed"), wx.OK | wx.ICON_ERROR, parent,
        )
        return False
