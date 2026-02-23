"""
ui/dialogs/rtl_tcp_dialog.py — Remote SDR server list manager.

Lets the user add, edit, remove, and test rtl_tcp servers.
Changes are applied immediately on each action.  The choice of which
server (or local SDR) to use is made in the RF Settings dialog.
"""

from __future__ import annotations

import socket
import struct
import threading

import wx
from accessibility import speech
from config.settings import Settings


class ServerEditDialog(wx.Dialog):
    """Small modal for adding or editing a single server entry."""

    def __init__(
        self,
        parent: wx.Window,
        title: str,
        name: str = "",
        host: str = "",
        port: int = 1234,
    ) -> None:
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        self.SetName(title)
        self._build_ui(name, host, port)
        self.Fit()
        self.Centre()

    def _build_ui(self, name: str, host: str, port: int) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label=_("Name:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._name_ctrl = wx.TextCtrl(self, value=name, name="Server name")
        grid.Add(self._name_ctrl, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label=_("Host:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._host_ctrl = wx.TextCtrl(self, value=host, name="Server host")
        grid.Add(self._host_ctrl, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label=_("Port:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._port_spin = wx.SpinCtrl(
            self, value=str(port), min=1, max=65535, name="Server port",
        )
        grid.Add(self._port_spin, 1, wx.EXPAND)

        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK)
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL))
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        host = self._host_ctrl.GetValue().strip()
        if not host:
            speech.output(_("Please enter a host address."))
            return
        self.EndModal(wx.ID_OK)

    def get_server(self) -> dict:
        name = self._name_ctrl.GetValue().strip()
        host = self._host_ctrl.GetValue().strip()
        return {
            "name": name or host,
            "host": host,
            "port": self._port_spin.GetValue(),
        }


class RtlTcpDialog(wx.Dialog):
    """Modal dialog for managing rtl_tcp remote servers.

    Changes are saved immediately on add/edit/remove — there is only
    a Close button, no OK/Cancel.
    """

    def __init__(self, parent: wx.Window, settings: Settings) -> None:
        super().__init__(
            parent,
            title=_("Remote SDR Servers"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("Remote SDR Servers")
        self._settings = settings
        self._build_ui()
        self.SetSize(480, 340)
        self.SetMinSize((400, 280))
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Server list
        self._list = wx.ListCtrl(
            panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Server list",
        )
        self._list.InsertColumn(0, _("Name"), width=160)
        self._list.InsertColumn(1, _("Host"), width=160)
        self._list.InsertColumn(2, _("Port"), width=70)
        self._populate_list()
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        # Action buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._add_btn = wx.Button(panel, label=_("&Add…"))
        self._edit_btn = wx.Button(panel, label=_("&Edit…"))
        self._remove_btn = wx.Button(panel, label=_("&Remove"))
        self._test_btn = wx.Button(panel, label=_("&Test Connection"))
        self._add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self._edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self._remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self._test_btn.Bind(wx.EVT_BUTTON, self._on_test)
        for btn in (self._add_btn, self._edit_btn, self._remove_btn, self._test_btn):
            btn_row.Add(btn, 0, wx.RIGHT, 6)
        sizer.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        self._update_buttons()
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._update_buttons())
        self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda e: self._update_buttons())
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit)

        # Close button only
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)

        close_btn = wx.Button(self, wx.ID_CLOSE, _("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        close_sizer = wx.BoxSizer(wx.HORIZONTAL)
        close_sizer.AddStretchSpacer()
        close_sizer.Add(close_btn, 0, wx.ALL, 8)
        dlg_sizer.Add(close_sizer, 0, wx.EXPAND)

        self.SetSizer(dlg_sizer)

    def _populate_list(self) -> None:
        self._list.DeleteAllItems()
        for srv in self._settings.rtl_tcp_servers:
            idx = self._list.InsertItem(self._list.GetItemCount(), srv.get("name", ""))
            self._list.SetItem(idx, 1, srv.get("host", ""))
            self._list.SetItem(idx, 2, str(srv.get("port", 1234)))

    def _update_buttons(self) -> None:
        has_sel = self._list.GetFirstSelected() != -1
        self._edit_btn.Enable(has_sel)
        self._remove_btn.Enable(has_sel)
        self._test_btn.Enable(has_sel)

    def _selected_index(self) -> int:
        return self._list.GetFirstSelected()

    def _save(self) -> None:
        """Persist after each change and fix active index if needed."""
        if self._settings.rtl_tcp_active >= len(self._settings.rtl_tcp_servers):
            self._settings.rtl_tcp_active = -1
        self._settings.save()

    def _on_add(self, _event: wx.CommandEvent) -> None:
        dlg = ServerEditDialog(self, _("Add Server"))
        if dlg.ShowModal() == wx.ID_OK:
            self._settings.rtl_tcp_servers.append(dlg.get_server())
            self._save()
            self._populate_list()
            self._list.Select(len(self._settings.rtl_tcp_servers) - 1)
        dlg.Destroy()

    def _on_edit(self, _event) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        srv = self._settings.rtl_tcp_servers[idx]
        dlg = ServerEditDialog(
            self, _("Edit Server"),
            name=srv.get("name", ""),
            host=srv.get("host", ""),
            port=srv.get("port", 1234),
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._settings.rtl_tcp_servers[idx] = dlg.get_server()
            self._save()
            self._populate_list()
            self._list.Select(idx)
        dlg.Destroy()

    def _on_remove(self, _event: wx.CommandEvent) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        name = self._settings.rtl_tcp_servers[idx].get("name", "")
        del self._settings.rtl_tcp_servers[idx]
        # Adjust active index
        active = self._settings.rtl_tcp_active
        if active == idx:
            self._settings.rtl_tcp_active = -1
        elif active > idx:
            self._settings.rtl_tcp_active = active - 1
        self._save()
        self._populate_list()
        self._update_buttons()
        speech.output(_("Removed {name}").format(name=name))

    def _on_test(self, _event: wx.CommandEvent) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        srv = self._settings.rtl_tcp_servers[idx]
        host = srv.get("host", "")
        port = srv.get("port", 1234)

        self._test_btn.Enable(False)
        speech.output(_("Testing connection to {host}:{port}…").format(
            host=host, port=port,
        ))
        threading.Thread(
            target=self._test_worker, args=(host, port),
            daemon=True, name="rtl_tcp_test",
        ).start()

    def _test_worker(self, host: str, port: int) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))

            header = b""
            while len(header) < 12:
                chunk = sock.recv(12 - len(header))
                if not chunk:
                    raise ConnectionError("Server closed during handshake")
                header += chunk

            magic = header[:4]
            if magic != b"RTL0":
                raise ConnectionError(f"Bad magic: {magic!r}")

            tuner_type = struct.unpack(">I", header[4:8])[0]
            gain_count = struct.unpack(">I", header[8:12])[0]
            sock.close()

            msg = _("Connection OK — tuner type {tuner}, {gains} gain steps.").format(
                tuner=tuner_type, gains=gain_count,
            )
            wx.CallAfter(self._test_done, msg, success=True)
        except Exception as exc:
            msg = _("Connection failed: {error}").format(error=exc)
            wx.CallAfter(self._test_done, msg, success=False)

    def _test_done(self, msg: str, success: bool) -> None:
        self._test_btn.Enable(True)
        speech.output(msg)
