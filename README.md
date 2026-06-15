# AccessDR

> **Note:** Early **beta** (0.7.0b1). Expect rough edges and breaking changes; translations are incomplete.

**[Documentation](https://ragb.github.io/accessdr/)** | **[Download](https://github.com/ragb/accessdr/releases/latest)**

Accessible SDR radio application designed for blind and visually impaired users. Screen reader driven, fully keyboard operated, with spectrum sonification. Built with Python, wxPython, and pyrtlsdr.

## Features

- **Full keyboard control & screen-reader output** (NVDA/JAWS) — every function is reachable and announced.
- **Baofeng-style VFO / Memory operation** — free-tune within a **band**, or step through numbered **channel** memories. The active tab is the mode, with a live context anchor in the title bar.
- **Bands** — service-grouped VFO presets (HF amateur, shortwave broadcast, CB, VHF/UHF) with per-band modulation, bandwidth and step, edited in a tree (++ctrl+shift+b++).
- **Channels** — numbered memory maps (PMR446 and CB CEPT ship by default), reorderable, with per-channel overrides (++ctrl+b++).
- **Modulations** — WFM (stereo + RDS), NFM (CTCSS), AM, USB, LSB, CW, DSB; modulation-specific settings live per band/channel.
- **HF reception** — RTL direct sampling and upconverter (Ham It Up / SpyVerter) support.
- **Spectrum sonification** — line graph + waterfall, an audible probe tone, and peak announcements.
- **Scanner**, **remote SDR** (rtl_tcp), **recording**, and **i18n** (English, plus partial Portuguese and French).

See the [keyboard shortcuts](https://ragb.github.io/accessdr/keyboard-shortcuts/) and [user guide](https://ragb.github.io/accessdr/user-guide/) for full details.

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
  operating_mode.py      # VFO / Memory (MR) state machine
accessibility/
  speech.py              # Screen reader output (accessible_output2)
  sonification.py        # Spectrum-to-audio tone mapping + probe tone
config/
  settings.py            # JSON-persisted settings
  bands.py               # Default band plan (seed table)
  scenes.py              # Band (VFO preset) model + store
  channels.py            # Channel memory model + maps
  mode_params.py         # Per-modulation settings registry
ui/
  main_window.py         # Primary window, VFO/Channels notebook
  keyboard_handler.py    # Keymap: (keycode, modifiers) -> action
  spectrum_panel.py      # Line graph + waterfall spectrogram display
  colormaps.py           # CVD-safe colormap LUTs (Viridis, Magma, Grayscale)
  panels/                # VFO band tree, channels & bands editors
  dialogs/               # RF, audio, spectrum, scanner, bands, modulation settings, help
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

Uses gettext. Portuguese (pt_PT) and French (fr) included (partial).

```bash
invoke i18n-build         # extract -> update -> compile (full pipeline)
# or step by step:
invoke i18n-extract       # update locale/accessdr.pot
# edit locale/<lang>/LC_MESSAGES/accessdr.po
invoke i18n-compile       # build .mo files
```

## About

AccessDR is an accessible software-defined radio application built for blind and visually impaired users. It provides full keyboard navigation, screen reader support, and spectrum sonification, making the world of radio monitoring accessible to everyone.

## Author

Created by [Rui Batista](https://github.com/ragb).

## License

MIT — see [LICENSE](LICENSE) for details.
