"""
i18n.py — Internationalisation bootstrap.

Call ``install(app)`` once inside ``App.OnInit`` (after the wx.App exists)
to activate gettext translations and set up wx.Locale.

Before this module runs, main.py installs no-op ``_()`` / ``N_()`` /
``ngettext()`` builtins so module-level strings can be marked for
translation at import time.
"""

from __future__ import annotations

import builtins
import gettext
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import wx

from config.paths import bundle_dir
from config.settings import Settings


def install(app: "wx.App") -> None:  # noqa: ARG001 – app reserved for future wx.Locale use
    """Activate translations for the configured language.

    * Looks for ``.mo`` files under ``<bundle_dir>/locale/<lang>/LC_MESSAGES/accessdr.mo``
    * Falls back to the source strings (English) when no catalogue is found.
    """
    settings = Settings.load()
    lang = settings.language or None  # None → system default

    locale_dir = os.path.join(bundle_dir(), "locale")

    try:
        translation = gettext.translation(
            "accessdr",
            localedir=locale_dir,
            languages=[lang] if lang else None,
        )
    except FileNotFoundError:
        # No .mo catalogue available — use null (passthrough) translation
        translation = gettext.NullTranslations()

    # Install _() and ngettext() as builtins
    translation.install()
    builtins.__dict__["ngettext"] = translation.ngettext
    # N_() is always a no-op marker for xgettext; keep it as-is
    builtins.__dict__["N_"] = lambda s: s
