# Settings Reference

AccessDR saves settings to a JSON file that persists across sessions. Settings are accessible through the menu dialogs or modified directly in the file.

Settings file location: `%LOCALAPPDATA%\AccessDR\settings.json`

## Radio Settings

Accessible via **Options > RF Settings** (++ctrl+r++).

| Setting | Default | Description |
|---|---|---|
| `frequency` | 98,100,000 Hz (98.1 MHz) | Current tuned frequency |
| `mode` | WFM | Demodulation mode |
| `bandwidth` | 200,000 Hz | Filter bandwidth |
| `sample_rate` | 2,400,000 sps | SDR sample rate |
| `gain` | 30.0 dB | Tuner gain (manual mode) |
| `ppm` | 0 | Frequency correction in parts per million |
| `step` | 1,000 Hz | Tuning step size |

## Audio Settings

Accessible via **Options > Audio Settings** (++ctrl+d++).

| Setting | Default | Description |
|---|---|---|
| `volume` | 0.75 | Output volume (0.0 to 1.0) |
| `squelch` | -80.0 dBm | Squelch threshold |
| `muted` | false | Mute state |
| `audio_device` | System default | Output audio device |
| `audio_buffer_size` | 4096 | Sounddevice block size in samples. Increase to 8192 or 16384 if you hear crackling. |

## Spectrum & Sonification

Accessible via **Tools > Spectrum & Sonification** (++ctrl+s++).

| Setting | Default | Description |
|---|---|---|
| `fft_size` | 1024 | FFT window size for spectrum analysis |
| `sonification_enabled` | false | Enable spectrum sonification |
| `sonification_min_hz` | 200 Hz | Pitch for weak signals (noise floor) |
| `sonification_max_hz` | 4000 Hz | Pitch for strong signals (full power) |
| `sonification_sweep_speed` | 5.0 s | Duration of one full spectrum sweep |
| `speech_peak_count` | 3 | Number of peaks announced when pressing ++f++ |
| `auto_announce_threshold` | -60.0 dBm | Signal level for automatic announcements |

## Language

| Setting | Default | Description |
|---|---|---|
| `language` | (system default) | UI language code (e.g. `pt_PT`). Leave empty for system default. |

## Troubleshooting

### Audio crackling

Increase `audio_buffer_size` to 8192 or 16384 via **Options > Audio Settings** (++ctrl+d++). Larger buffers add a small amount of latency but eliminate crackling on slower systems.

### Frequency offset

If stations appear slightly off-frequency, adjust the `ppm` setting in **Options > RF Settings** (++ctrl+r++). A typical RTL-SDR dongle drifts by 1-60 ppm. Use a known reference signal (e.g. a local FM station) to calibrate.
