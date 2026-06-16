# Building from Source

## Prerequisites

- Python 3.12 or later
- Git
- [NSIS](https://nsis.sourceforge.io/Download) (only for building the Windows installer)

## Setup

```bash
git clone https://github.com/ragb/accessdr.git
cd accessdr
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Build Tasks

AccessDR uses [Invoke](https://www.pyinvoke.org/) for build automation. Run `invoke --list` to see all available tasks.

### Fetch RTL-SDR Library

```bash
invoke fetch-dlls
```

Downloads the static librtlsdr build from GitHub. Skips the download if the DLL is already present. This is required before running the app or building.

### Run from Source

```bash
invoke run
```

Or directly:

```bash
python main.py
```

### Build Executable

```bash
invoke build
```

This runs the full pipeline: fetch DLLs, compile translations, then freeze the app with PyInstaller. Output: `dist\AccessDR\AccessDR.exe`

### Build Installer

```bash
invoke installer
```

Runs the full build, then creates an NSIS installer. Requires NSIS to be installed. Output: `dist\installer\AccessDR-<version>-setup.exe`

### Clean Build Artifacts

```bash
invoke clean
```

Removes `build/`, `dist/`, and compiled `.mo` translation files.

## Translations

AccessDR uses GNU gettext for internationalisation.

### Add a New Language

```bash
invoke i18n-extract
invoke i18n-init --lang=fr_FR
```

This creates `locale/fr_FR/LC_MESSAGES/accessdr.po`. Translate the strings in that file, then compile:

```bash
invoke i18n-compile
```

### Update Existing Translations

After changing translatable strings in the source code:

```bash
invoke i18n-build
```

This extracts new strings, updates existing `.po` files, and compiles to `.mo`.

## Continuous Integration

The GitHub Actions workflow (`.github/workflows/build.yml`) automatically:

- Builds the installer on every push to `master`
- Attaches the installer to GitHub releases when a release is published

## Project Structure

```
accessdr/
  main.py                  # Entry point
  core/
    sdr_device.py          # RTL-SDR hardware abstraction
    audio.py               # Audio output via sounddevice
    scanner.py             # Frequency scanner
    dsp/
      demodulator.py       # WFM/NFM/AM/SSB/CW demodulators
      filters.py           # Decimation and filtering
      spectrum.py          # FFT spectrum analyser
  accessibility/
    speech.py              # Screen reader output
    sonification.py        # Spectrum-to-audio tone mapping
  config/
    settings.py            # JSON-persisted settings
    bands.py               # Default band plan definitions
    scenes.py              # Band (VFO preset) model + persistence
    channels.py            # Channel memory model + persistence
    mode_params.py         # Per-modulation settings registry
    modes.py               # Modulation, bandwidth, and step constants
    paths.py               # App data paths
  ui/
    main_window.py         # Primary window
    dialogs/               # Settings and tool dialogs
  locale/                  # Translations (.po/.mo)
  installer/               # NSIS installer script
  docs/                    # Documentation (MkDocs)
```
