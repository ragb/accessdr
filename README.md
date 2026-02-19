# AccessDR

Accessible SDR radio application for blind and visually impaired users. Built with Python, wxPython, and pyrtlsdr.

AccessDR brings software-defined radio to screen reader users with full keyboard navigation, speech output via NVDA/JAWS/Narrator, and spectrum sonification that lets you *hear* the RF spectrum as a sweeping tone.

## Features

- **Full screen reader support** — all controls, status changes, and signal information are spoken aloud via [accessible_output2](https://pypi.org/project/accessible_output2/) (works with NVDA, JAWS, Windows Narrator, and others)
- **7 demodulation modes** — WFM (stereo), NFM, AM, USB, LSB, CW, DSB
- **Spectrum sonification** — converts FFT data into a pitched tone sweep so you can explore the RF spectrum by ear; supports continuous sweep and on-demand snapshots
- **Frequency scanner** — scans a range and announces signals above squelch threshold
- **Bookmarks** — save and recall favourite frequencies with mode
- **Band presets** — quick-jump to AM Broadcast, FM Broadcast, Air Band, 2m/70cm Amateur, NOAA Weather, Marine VHF, PMR446, and more
- **Configurable audio** — adjustable buffer size, volume, squelch, and output device
- **Internationalisation** — gettext-based i18n with Portuguese (pt-PT) translation included
- **Windows installer** — NSIS installer script included for distribution

## Requirements

- **OS:** Windows 10/11
- **Hardware:** RTL-SDR dongle (e.g. NESDR SMArt v5, any RTL2832U-based device)
- **Driver:** WinUSB driver installed for the dongle (use [Zadig](https://zadig.akeo.ie/) if needed)
- **Python:** 3.12+

## Installation

### From source

```bash
git clone https://github.com/user/accessdr.git
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

## Keyboard Shortcuts

### Main Window

| Key | Action |
|---|---|
| R | Start / Stop radio |
| Up / Down | Tune up / down by step |
| Ctrl+Up / Ctrl+Down | Tune up / down by 10x step |
| S | Cycle tuning step size |
| M | Mute / Unmute |
| I | Read signal strength and status |
| F | Speak top spectrum peaks |
| Space | Sonification snapshot sweep |

### Demodulation Modes

| Key | Mode |
|---|---|
| W | Wide FM |
| N | Narrow FM |
| A | AM |
| U | USB |
| L | LSB |
| C | CW |
| D | DSB |

### Dialogs

| Key | Dialog |
|---|---|
| Ctrl+R | RF Settings |
| Ctrl+S | Spectrum & Sonification |
| Ctrl+N | Scanner |
| Ctrl+B | Bookmarks |
| Ctrl+D | Audio Settings |
| F1 | Keyboard Shortcuts help |

### Scanner (when open)

| Key | Action |
|---|---|
| H | Hold on frequency |
| K | Skip to next |
| Escape | Stop scan |

## Architecture

```
accessdr/
  main.py                  # Entry point, wx.App
  core/
    sdr_device.py          # RTL-SDR hardware abstraction + IQ capture thread
    audio.py               # Audio output via sounddevice
    dsp/
      demodulator.py       # Stateful WFM/NFM/AM/SSB/CW demodulators
      filters.py           # Decimation and filtering
      spectrum.py          # FFT spectrum analyser with peak detection
    scanner.py             # Frequency scanner
  accessibility/
    speech.py              # Screen reader speech output (accessible_output2)
    sonification.py        # Spectrum-to-audio tone mapping
  config/
    settings.py            # JSON-persisted settings dataclass
    bookmarks.py           # Bookmark storage
    bands.py               # Band definitions (AM, FM, Air, VHF, etc.)
    paths.py               # App data directory paths
  ui/
    main_window.py         # Primary window with radio controls
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
  -> demodulate (stateful, filter state carried between chunks)
  -> resample_poly -> 48 kHz audio
  -> sounddevice output
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

Output: `dist\installer\AccessDR-0.1.0-setup.exe`

## License

MIT
