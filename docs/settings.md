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

## Operating Mode (VFO / Memory)

AccessDR works like a handheld: a **VFO** mode for free tuning within a band, and a **Memory (MR)** mode for stepping through numbered channels. The active notebook tab selects the mode, and the choice plus your position is restored on the next launch. See the [Channels and Bands](user-guide.md#channels-and-bands) section of the User Guide.

| Setting | Default | Description |
|---|---|---|
| `op_mode` | VFO | Operating mode: `VFO` (band tuning) or `MR` (memory channels). |
| `active_scene` | "" (Free / Full Range) | Name of the active band. Empty selects the built-in Free / Full Range band. |
| `active_channel` | 0 | Index of the active channel within the active channel map (Memory mode). |

The band plan is stored in `scenes.json` and the channel maps in `channels.json`, both in the same folder as `settings.json`. Edit them in the app via **Radio > Bands…** (++ctrl+shift+b++) and the **Channels** tab (++ctrl+b++).

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

Accessible via **Options > Spectrum Settings** (++ctrl+s++).

| Setting | Default | Description |
|---|---|---|
| `fft_size` | 1024 | FFT window size for spectrum analysis |
| `sonification_enabled` | false | Enable spectrum sonification |
| `sonification_min_hz` | 200 Hz | Pitch for weak signals (noise floor) |
| `sonification_max_hz` | 4000 Hz | Pitch for strong signals (full power) |
| `sonification_sweep_speed` | 5.0 s | Duration of one full spectrum sweep |
| `speech_peak_count` | 3 | Number of peaks announced when pressing ++f++ |
| `auto_announce_threshold` | -60.0 dBm | Signal level for automatic announcements |

## RF Settings (continued)

Also accessible via **Options > RF Settings** (++ctrl+r++).

| Setting | Default | Description |
|---|---|---|
| `noise_blanker_enabled` | false | Enable impulse noise blanker on raw IQ |
| `noise_blanker_threshold` | 5.0 | Blanker threshold (multiplier above median magnitude) |
| `bias_tee` | false | Enable Bias Tee DC power on antenna connector. WARNING: can damage incompatible devices. |
| `direct_sampling` | 0 | RTL2832U direct-sampling mode for HF: 0 = off, 1 = I-branch, 2 = Q-branch. No effect on SDRs that tune HF natively. |
| `upconverter_offset` | 0 | Hz added to the hardware LO when using an upconverter (e.g. 125000000 for Ham It Up). 0 = no upconverter. The app keeps showing the real HF frequency. |

## Waterfall Display

Accessible via **Options > Spectrum Settings** (++ctrl+s++).

| Setting | Default | Description |
|---|---|---|
| `waterfall_colormap` | Viridis | Colour scheme for the waterfall: `Viridis` (CVD-safe, perceptually uniform), `Magma` (high-contrast dark-to-bright), `Grayscale` (pure black-to-white) |
| `waterfall_db_floor` | -90.0 dB | Maps to the darkest colour (LUT index 0). Lower values reveal weaker signals. |
| `waterfall_db_ceiling` | -20.0 dB | Maps to the brightest colour (LUT index 255). The range ceiling − floor controls contrast. |

The waterfall is always displayed below the line graph. The top 40% of the spectrum panel shows the line graph, and the bottom 60% shows the waterfall spectrogram scrolling newest-at-top. All three colour schemes are designed to be safe for colour-blind users (CVD-safe).

## Modulation Settings

These are the **built-in defaults** for each modulation. They are no longer edited from a global menu dialog. Instead, each **Modulation:** selector (on the VFO tab, in the Bands form, and in the Channels form) has a **Settings…** button beside it, enabled only when the current modulation has settings. On the VFO tab the button edits these defaults; on a band or channel it edits per-band / per-channel **overrides** (where a blank/default value means "inherit the built-in default below"). See the [Modulation Settings](user-guide.md#modulation-settings) section of the User Guide.

### NFM

| Setting | Default | Description |
|---|---|---|
| `nfm_deviation` | 5000 Hz | FM deviation: 5000 Hz (standard 25 kHz channels) or 2500 Hz (PMR446 12.5 kHz channels) |
| `nfm_ctcss_notch` | true | Remove detected CTCSS sub-audible tone from audio output. Eliminates the low-frequency hum on channels that use tone squelch. |

### WFM

| Setting | Default | Description |
|---|---|---|
| `wfm_deemphasis` | auto | De-emphasis time constant: `auto` (detect by region), `50` (50 us, Europe), `75` (75 us, Americas) |
| `wfm_stereo_mode` | auto | Stereo decoding: `auto` (pilot detection), `mono` (force mono), `stereo` (force stereo) |
| `wfm_hiblend_enabled` | true | Reduce treble on weak signals to cut FM hiss |
| `wfm_rds_enabled` | true | Decode RDS station name and radio text |

AM, USB, LSB, CW, and DSB have no modulation-specific settings, and their Settings… button is disabled.

## Remote SDR (rtl_tcp)

Accessible via **Options > Remote SDR** (++ctrl+g++). Also affects the device list in **Options > RF Settings** (++ctrl+r++).

| Setting | Default | Description |
|---|---|---|
| `rtl_tcp_servers` | [] (empty) | List of remote rtl_tcp servers. Each entry has a name, host, and port. |
| `rtl_tcp_active` | -1 (local) | Index of the active remote server, or -1 to use the local USB dongle. |

When one or more servers are configured, they appear in the RF Settings device dropdown alongside any local USB devices. Selecting a remote server switches the backend to rtl_tcp; selecting a local device switches back.

Use the Remote SDR Servers dialog (++ctrl+g++) to add, edit, remove, and test servers. Changes are saved immediately on each action.

## Language

| Setting | Default | Description |
|---|---|---|
| `language` | (system default) | UI language code (e.g. `pt_PT`). Leave empty for system default. |

## Troubleshooting

### Audio crackling

Increase `audio_buffer_size` to 8192 or 16384 via **Options > Audio Settings** (++ctrl+d++). Larger buffers add a small amount of latency but eliminate crackling on slower systems.

### Frequency offset

If stations appear slightly off-frequency, adjust the `ppm` setting in **Options > RF Settings** (++ctrl+r++). A typical RTL-SDR dongle drifts by 1-60 ppm. Use a known reference signal (e.g. a local FM station) to calibrate.
