# AccessDR

> **Note:** This project is a proof of concept in a very early alpha stage. Expect rough edges, missing features, and breaking changes.

**[Documentation](https://ragb.github.io/accessdr/)** | **[Download](https://github.com/ragb/accessdr/releases/latest)**

Accessible SDR radio application for blind and visually impaired users. Built with Python, wxPython, and pyrtlsdr.

AccessDR brings software-defined radio to screen reader users with full keyboard navigation, speech output via NVDA/JAWS/Narrator, and spectrum sonification that lets you *hear* the RF spectrum.

## Key Features

### Accessibility

- **Screen reader support** — every control, frequency change, signal reading, and status update is spoken aloud via [accessible_output2](https://pypi.org/project/accessible_output2/), compatible with NVDA, JAWS, Windows Narrator, and others
- **Complete keyboard operation** — no mouse required; all radio functions have keyboard shortcuts with consistent, discoverable bindings (press F1 for a full reference)
- **Spectrum sonification** — converts the FFT spectrum into a pitched stereo tone sweep so you can explore the RF band by ear; supports snapshot and continuous sweep modes
- **Interactive spectrum cursor** — hold Ctrl to hear a probe tone at any point in the spectrum; move with arrow keys, pitch encodes signal strength, stereo pan encodes frequency position
- **Spoken signal reports** — press I for instant signal strength (dBFS + S-meter), stereo/mono state, squelch status, and demod offset; press F for peak frequencies; press T for cursor position
- **Auto-announce** — configurable threshold to automatically speak strong signals as they appear
- **Pause and explore** — press Space to freeze the radio; the last spectrum stays fully navigable (cursor, probe, peaks, zoom) so you can examine a moment in time without the signal changing

### Radio

- 7 demodulation modes — WFM (with stereo decoding), NFM, AM, USB, LSB, CW, DSB
- Software VFO offset — shift the demodulator within the visible spectrum without retuning hardware
- Frequency scanner — scans a range and announces signals above squelch threshold
- Band presets — quick-jump to AM/FM Broadcast, Air Band, 2m/70cm Amateur, NOAA Weather, Marine VHF, PMR446, and more
- Bookmarks — save and recall favourite frequencies with mode
- Configurable audio — WASAPI output, adjustable buffer size, volume, squelch, and device selection
- Internationalisation — gettext-based i18n with Portuguese (pt_PT) translation included
- Windows installer — NSIS installer script included for distribution

## Requirements

- **OS:** Windows 10/11
- **Hardware:** RTL-SDR dongle (e.g. NESDR SMArt v5, any RTL2832U-based device)
- **Driver:** WinUSB driver installed for the dongle (use [Zadig](https://zadig.akeo.ie/) if needed)
- **Python:** 3.12+

## Installation

### From source

```bash
git clone https://github.com/ragb/accessdr.git
cd accessdr
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Fetch the RTL-SDR library:

```bash
invoke fetch-dlls
```

This downloads the static librtlsdr build automatically. Alternatively, copy `rtlsdr.dll` manually from [SDR#](https://airspy.com/download/) or the [librtlsdr releases](https://github.com/librtlsdr/librtlsdr/releases).

### Running

```bash
python main.py
```

## Quick Start

1. Connect your RTL-SDR dongle
2. Launch AccessDR — you'll hear "Ready — no device connected"
3. Press **F2** to start the radio — audio begins and "Radio started" is announced
4. Use **Up/Down arrows** to tune (press **S** to change step size)
5. Press **M** then a mode letter to switch demodulation (e.g. M then W for FM broadcast)
6. Press **F5** to hear a sonification sweep of the spectrum
7. Hold **Ctrl** to probe the spectrum with a tone; add **Left/Right** to move through it
8. Press **Space** to pause, explore the frozen spectrum, then **Space** to resume
9. Press **F1** for the full keyboard shortcut reference

See the [User Guide](https://ragb.github.io/accessdr/user-guide/) and [Keyboard Shortcuts](https://ragb.github.io/accessdr/keyboard-shortcuts/) for complete documentation.

## Architecture

```
accessdr/
  main.py                  # Entry point, wx.App
  core/
    sdr_device.py          # RTL-SDR hardware abstraction + IQ capture thread
    audio.py               # Audio output via sounddevice (WASAPI)
    dsp/
      demodulator.py       # Stateful WFM/NFM/AM/SSB/CW demodulators
      filters.py           # Decimation and filtering
      mixer.py             # Software VFO offset mixer
      spectrum.py          # FFT spectrum analyser with peak detection
    scanner.py             # Frequency scanner
  accessibility/
    speech.py              # Screen reader speech output (accessible_output2)
    sonification.py        # Spectrum-to-audio tone mapping + probe tone
  config/
    settings.py            # JSON-persisted settings dataclass
    bookmarks.py           # Bookmark storage
    bands.py               # Band definitions (AM, FM, Air, VHF, etc.)
    paths.py               # App data directory paths
  ui/
    main_window.py         # Primary window with radio controls
    spectrum_panel.py      # Visual spectrum display with cursor
    dialogs/
      rf_dialog.py         # RF settings (gain, PPM, sample rate)
      audio_dialog.py      # Audio settings (device, buffer size)
      spectrum_dialog.py   # Spectrum & sonification controls
      scanner_dialog.py    # Frequency scanner UI
      bookmarks_dialog.py  # Bookmark manager
      help_dialog.py       # Keyboard shortcut reference
  locale/                  # Translations (gettext .po/.mo)
  installer/               # NSIS installer script
```

### DSP Pipeline

```
RTL-SDR @ 2.4 MSPS
  -> decimate x10 -> 240 kSPS baseband
  -> software mixer (VFO offset) -> shift to DC
  -> demodulate (stateful, filter state carried between chunks)
  -> resample_poly -> 48 kHz stereo audio
  -> sounddevice WASAPI output
```

All cross-thread communication uses `queue.Queue` and `wx.CallAfter`. Live tuning calls go through raw librtlsdr C functions for thread safety while `read_samples` blocks.

## Building a Distributable

The project uses [Invoke](https://www.pyinvoke.org/) for build tasks. Run `invoke --list` to see all available tasks.

```bash
invoke fetch-dlls    # download RTL-SDR DLLs (skips if already present)
invoke build         # fetch DLLs + compile translations + PyInstaller freeze
invoke installer     # full build + NSIS installer
invoke clean         # remove build artifacts
```

The `invoke build` command automatically downloads the RTL-SDR static library from the [librtlsdr releases](https://github.com/librtlsdr/librtlsdr/releases), so manually placing DLLs is only needed when running from source.

NSIS must be installed for `invoke installer` ([download](https://nsis.sourceforge.io/Download)).

## License

MIT
