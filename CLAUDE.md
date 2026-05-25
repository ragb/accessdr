# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this?

AccessDR — accessible SDR radio app for blind/visually impaired users. Windows-only, wxPython UI, full keyboard navigation, screen reader support (NVDA/JAWS), spectrum sonification. Python 3.12+, pyrtlsdr, RTL-SDR hardware.

## Commands

```bash
# Run from source
.venv\Scripts\python.exe main.py

# Tests
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe -m pytest tests/test_rds.py -v              # single file
.venv\Scripts\python.exe -m pytest tests/test_rds.py::test_name -v   # single test

# i18n (always run i18n-build before release or after changing translatable strings)
invoke i18n-build          # full pipeline: extract → update → compile
invoke i18n-extract        # extract strings to .pot
invoke i18n-update         # merge .pot into .po files
invoke i18n-compile        # compile .po → .mo

# Build & package
invoke fetch-dlls          # download librtlsdr DLLs
invoke build               # DLLs + i18n + PyInstaller freeze
invoke installer           # full build + NSIS installer
invoke clean               # remove build artifacts
```

## Architecture

### Threading model

Three threads communicate via `queue.Queue` + `wx.CallAfter`:
- **Main thread**: wxPython UI, keyboard dispatch, dialogs
- **SDR capture thread**: reads IQ samples at 2.4 MSPS via `read_samples_async`, feeds DSP pipeline callback
- **Audio thread**: sounddevice callback drains sample queue, outputs via WASAPI

### DSP pipeline (`core/dsp/`)

```
IQ @ 2.4 MSPS → noise_blanker → decimate ×10 → 240 kSPS → mixer (VFO offset)
  → demodulator (WFM/NFM/AM/SSB/CW) → resample_poly → 48 kHz → audio output
```

- Demodulators are **stateful** — carry `lfilter` zi between chunks to avoid boundary crackling
- Filters pre-computed once at construction via `make_demodulator(mode, baseband_rate)`
- `zero_phase=False` everywhere (True doubles cost, non-causal)
- Use `resample_poly` not `resample` for the 240k→48k step

### SDR backends (`core/sdr_backends.py`) — strategy pattern

`PyRtlSdrBackend`, `SoapySDRBackend`, `RtlTcpBackend`, `DummyBackend` — each implements `open()`, `close()`, `stream_loop()`, `set_frequency()`, etc.

### Keyboard handling

`ui/keyboard_handler.py` maps `(keycode, modifiers) → action_name` → dispatched in `MainWindow._on_key()`.

### Settings

`config/settings.py` — `@dataclass` with JSON persistence (`settings.json`). All app state survives restarts.

## pyrtlsdr quirks (critical)

- Import: `from rtlsdr.rtlsdr import RtlSdr` (base class). Do NOT use `rtlsdr.RtlSdr` — resolves to `RtlSdrAio` (async, breaks sync reads).
- Device handle attribute is `dev_p` (not `dev`) in pyrtlsdr 0.3.0.
- Skip `freq_correction = 0` — causes `LIBUSB_ERROR_INVALID_PARAM`.
- Live tuning during capture uses raw C calls — pyrtlsdr wrappers call `self.close()` on error, unsafe from UI thread.
- Cross-thread `rtlsdr_cancel_async` causes access violation on Windows/WinUSB — cancel only from callback thread.

## RDS decoder (`core/dsp/rds.py`)

- Real-only product demodulation (differential BPSK XOR cancels carrier phase offset)
- Pilot-derived carrier: `cos(3θ) = 4cos³(θ) − 3cos(θ)`
- FIR BPF 55.5–58.5 kHz (501-tap Kaiser, 97 dB rejection) — previous IIR had only 10.5 dB
- CRC-10 polynomial `0x5B9`, shift `i-10`
- Decodes PS, PTY, RT from groups 0A/0B and 2A/2B

## i18n

Babel-based gettext. Strings marked with `_("...")` and `N_("...")`. Portuguese (pt_PT) included. Locale files in `locale/<lang>/LC_MESSAGES/`. Always compile `.mo` files before release.
