# AccessDR

> **Note:** This project is a proof of concept in a very early alpha stage. Expect rough edges, missing features, and breaking changes.

**[Documentation](https://ragb.github.io/accessdr/)** | **[Download](https://github.com/ragb/accessdr/releases/latest)**

Accessible SDR radio application designed for blind and visually impaired users. Screen reader driven, fully keyboard operated, with spectrum sonification. Built with Python, wxPython, and pyrtlsdr.

## Development Setup

Requires Windows 10/11, Python 3.12+, and an RTL-SDR dongle with WinUSB driver ([Zadig](https://zadig.akeo.ie/)).

```bash
git clone https://github.com/ragb/accessdr.git
cd accessdr
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
invoke fetch-dlls
python main.py
```

`invoke fetch-dlls` downloads the librtlsdr static build. Alternatively, copy `rtlsdr.dll` from [librtlsdr releases](https://github.com/librtlsdr/librtlsdr/releases).

## Architecture

```
core/
  sdr_device.py          # RTL-SDR abstraction + IQ capture thread
  audio.py               # WASAPI audio output via sounddevice
  dsp/
    demodulator.py       # Stateful WFM/NFM/AM/SSB/CW demodulators
    filters.py           # Decimation and filtering
    mixer.py             # Software VFO offset mixer
    noise_blanker.py     # Impulse noise blanker (median + interpolation)
    ctcss.py             # CTCSS tone detector (generalized Goertzel)
    rds.py               # RDS/RBDS decoder (PS, RT, PTY)
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
  spectrum_panel.py      # Line graph + waterfall spectrogram display
  colormaps.py           # CVD-safe colormap LUTs (Viridis, Magma, Grayscale)
  dialogs/               # RF, audio, spectrum, scanner, bookmarks, help
locale/                  # Translations (gettext .po/.mo)
installer/               # NSIS installer script
```

### DSP Pipeline

```
RTL-SDR @ 2.4 MSPS
  → noise blanker (impulse suppression)
  → decimate ×10 → 240 kSPS baseband
  → software mixer (VFO offset)
  → demodulate (stateful filters)
      WFM: stereo blend + RDS decode
      NFM: CTCSS tone detect
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

Uses gettext. Portuguese (pt_PT) included.

```bash
invoke extract-messages   # update locale/accessdr.pot
# edit locale/pt_PT/LC_MESSAGES/accessdr.po
invoke compile-messages   # build .mo files
```

## License

MIT
