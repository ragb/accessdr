# AccessDR

> **Note:** This project is a proof of concept in a very early alpha stage. Expect rough edges, missing features, and breaking changes.

**[Documentation](https://ragb.github.io/accessdr/)** | **[Download](https://github.com/ragb/accessdr/releases/latest)**

Accessible SDR radio application for blind and visually impaired users. Built with Python, wxPython, and pyrtlsdr.

## Features

- **Fully accessible** — complete keyboard navigation, screen reader output (NVDA, JAWS, Narrator), and spectrum sonification so you can explore RF signals by ear
- **7 demodulation modes** — WFM (stereo), NFM, AM, USB, LSB, CW, DSB with software VFO offset
- **Spectrum tools** — interactive probe tone, peak detection, zoom, frequency scanner, and pause-to-explore
- **Portable** — single RTL-SDR dongle, no additional dependencies beyond Python

See the [User Guide](https://ragb.github.io/accessdr/user-guide/) and [Keyboard Shortcuts](https://ragb.github.io/accessdr/keyboard-shortcuts/) for usage documentation.

## Requirements

- **OS:** Windows 10/11
- **Hardware:** RTL-SDR dongle (any RTL2832U-based device)
- **Driver:** WinUSB (use [Zadig](https://zadig.akeo.ie/) if needed)
- **Python:** 3.12+

## Getting Started

```bash
git clone https://github.com/ragb/accessdr.git
cd accessdr
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
invoke fetch-dlls
python main.py
```

`invoke fetch-dlls` downloads the librtlsdr static build. Alternatively, copy `rtlsdr.dll` from [SDR#](https://airspy.com/download/) or [librtlsdr releases](https://github.com/librtlsdr/librtlsdr/releases).

## Architecture

```
core/
  sdr_device.py          # RTL-SDR abstraction + IQ capture thread
  audio.py               # WASAPI audio output via sounddevice
  dsp/
    demodulator.py       # Stateful WFM/NFM/AM/SSB/CW demodulators
    filters.py           # Decimation and filtering
    mixer.py             # Software VFO offset mixer
    spectrum.py          # FFT spectrum analyser + peak detection
  scanner.py             # Frequency scanner
accessibility/
  speech.py              # Screen reader output (accessible_output2)
  sonification.py        # Spectrum-to-audio tone mapping + probe tone
config/
  settings.py            # JSON-persisted settings
  bookmarks.py           # Bookmark storage
  bands.py               # Band definitions
ui/
  main_window.py         # Primary window + keyboard shortcuts
  spectrum_panel.py      # Visual spectrum display with cursor
  dialogs/               # RF, audio, spectrum, scanner, bookmarks, help
locale/                  # Translations (gettext .po/.mo)
installer/               # NSIS installer script
```

### DSP Pipeline

```
RTL-SDR @ 2.4 MSPS
  → decimate ×10 → 240 kSPS baseband
  → software mixer (VFO offset)
  → demodulate (stateful filters)
  → resample_poly → 48 kHz stereo
  → sounddevice WASAPI output
```

Cross-thread communication uses `queue.Queue` + `wx.CallAfter`. Live tuning goes through raw librtlsdr C calls for thread safety while `read_samples` blocks.

## Building

```bash
invoke fetch-dlls    # download RTL-SDR DLLs
invoke build         # DLLs + translations + PyInstaller freeze
invoke installer     # full build + NSIS installer
invoke clean         # remove build artifacts
```

NSIS required for `invoke installer` ([download](https://nsis.sourceforge.io/Download)).

## Internationalisation

Uses gettext. Portuguese (pt_PT) included. Extract → translate → compile:

```bash
invoke extract-messages   # update locale/accessdr.pot
# edit locale/pt_PT/LC_MESSAGES/accessdr.po
invoke compile-messages   # build .mo files
```

## License

MIT
