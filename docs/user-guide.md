# User Guide

## Tuning

### Frequency Entry

Press ++ctrl+q++ to open the LO frequency entry dialog. Press ++q++ to hear the current LO frequency, or ++o++ to hear the listening (demod) frequency. Press ++ctrl+o++ to enter a listening frequency directly — AccessDR calculates the offset from the LO automatically.

Enter a frequency in one of these formats:

- **MHz** (most common): `98.1` or `98.1 MHz`
- **kHz**: values between 30,000 and 30,000,000 are treated as kHz
- **Hz**: values above 30,000,000 are treated as Hz

Press ++enter++ to confirm or ++escape++ to cancel.

### Step Tuning

Use ++up++ and ++down++ to tune by the current step size. Hold ++shift++ to tune by 10x the step size.

Press ++s++ to cycle through step sizes:

| Step | Use case |
|---|---|
| 1 Hz | Fine CW/SSB tuning |
| 10 Hz | SSB tuning |
| 100 Hz | SSB/AM fine tuning |
| 1 kHz | AM broadcast |
| 10 kHz | Default general tuning |
| 100 kHz | FM broadcast scanning |
| 1 MHz | Quick band scanning |

### Pause / Resume

Press ++space++ to **pause** the radio — IQ capture and audio stop, but the last spectrum snapshot remains visible and navigable. Cursor movement, probe tone, peaks, zoom and all other spectrum features continue to work on the frozen data. Press ++space++ again to **resume** reception. Press ++f2++ while paused to fully stop the radio and release the device.

### Band Presets

Open the **Radio > Bands** menu (++alt+r++) to jump to a preset band. Each preset tunes to the band's centre frequency and sets the appropriate demodulation mode.

Available bands:

| Band | Frequency Range | Mode |
|---|---|---|
| AM Broadcast | 530 kHz - 1.71 MHz | AM |
| FM Broadcast | 87.5 - 108 MHz | WFM |
| Air Band | 108 - 137 MHz | AM |
| 2m Amateur | 144 - 148 MHz | NFM |
| NOAA Weather | 162.4 - 162.55 MHz | NFM |
| Marine VHF | 156 - 174 MHz | NFM |
| UHF CB | 462.55 - 467.73 MHz | NFM |
| 70cm Amateur | 420 - 450 MHz | NFM |
| PMR446 | 446.0 - 446.2 MHz | NFM |

## Demodulation Modes

Press ++m++ to enter mode selection, then press the mode letter:

| Key | Mode |
|---|---|
| ++m++ ++w++ | WFM — Wideband FM |
| ++m++ ++n++ | NFM — Narrowband FM |
| ++m++ ++a++ | AM — Amplitude Modulation |
| ++m++ ++u++ | USB — Upper Sideband |
| ++m++ ++l++ | LSB — Lower Sideband |
| ++m++ ++c++ | CW — Continuous Wave (Morse) |
| ++m++ ++d++ | DSB — Double Sideband |

Each mode has selectable filter bandwidths in the main window's BW dropdown.

### WFM — Wideband FM

The standard mode for **FM broadcast radio** (87.5–108 MHz). Uses a 200 kHz channel and includes stereo decoding — AccessDR automatically detects and announces stereo or mono. This is the default mode and the best starting point for new users. Typical bandwidth: 150–200 kHz.

WFM includes several sub-features configurable via **Options > WFM Settings** (++ctrl+w++):

- **De-emphasis** — compensates for the FM pre-emphasis curve. Set to Auto (detects your region), 50 us (Europe/Asia), or 75 us (Americas/South Korea). Wrong de-emphasis makes audio sound too bright or too dull.
- **Stereo mode** — Auto detects the 19 kHz pilot and blends between mono and stereo based on signal quality. Force Mono disables stereo decoding (quieter on weak signals). Force Stereo always decodes stereo regardless of signal quality.
- **Hi-blend** — automatically reduces treble on weak stereo signals to cut FM hiss. Disable if you prefer full-bandwidth audio regardless of signal strength.
- **RDS decoding** — extracts station name (PS), radio text (RT), and program type from the RDS subcarrier at 57 kHz. When enabled, the station name is announced automatically on tune. Press ++i++ to hear RDS info. Disable to save a small amount of CPU.

### NFM — Narrowband FM

Used by most **two-way radio** systems: amateur (ham) radio repeaters, PMR446 walkie-talkies, marine VHF, NOAA weather radio, taxi and business radios, and public safety communications. NFM channels are much narrower than broadcast FM (12.5 or 25 kHz), so you will hear a single voice conversation rather than a music station. Set the step size to 12.5 or 25 kHz when scanning for NFM signals.

NFM includes **CTCSS tone detection** — when a repeater or radio system uses a sub-audible tone (67.0–254.1 Hz) for access control, AccessDR detects and reports the tone. Press ++i++ to hear the detected CTCSS tone along with signal information.

A **CTCSS notch filter** automatically removes the detected sub-audible tone from the audio output, eliminating the low-frequency hum that can be distracting on speakers or headphones with good bass response. The notch filter is enabled by default and can be toggled in **Options > NFM Settings** (++ctrl+shift+n++).

### AM — Amplitude Modulation

Used for **AM broadcast radio** (530 kHz–1.71 MHz), **aviation communications** (108–137 MHz air band), and **shortwave broadcasts**. AM is simpler than FM and works well over long distances, which is why it is used for aircraft and international broadcasting. Typical bandwidth: 6–10 kHz.

### USB — Upper Sideband

A form of **single sideband** (SSB) modulation used by amateur (ham) radio operators on **HF frequencies above 10 MHz** and on **VHF/UHF**. SSB transmits only one half of the AM signal, making it more power-efficient and spectrally compact. Conversations sound distorted if you are slightly off frequency — tune in 100 Hz or 10 Hz steps until voices sound natural. Typical bandwidth: 2.7 kHz.

### LSB — Lower Sideband

The mirror image of USB, used by amateur radio operators on **HF frequencies below 10 MHz** (e.g. the 80m and 40m bands). The convention is: LSB below 10 MHz, USB above 10 MHz. Tuning technique is the same as USB. Typical bandwidth: 2.7 kHz.

### CW — Continuous Wave (Morse Code)

Used for **Morse code** (CW) transmissions. CW uses an extremely narrow filter (250–500 Hz) centred on a single tone, so you hear individual dits and dahs clearly while rejecting nearby signals. Common on amateur HF bands, especially during contests and low-power (QRP) operation. Tune slowly in 10 Hz or 1 Hz steps to centre the tone.

### DSB — Double Sideband

Similar to AM but **without carrier filtering**. Useful for receiving AM signals that don't quite fit the standard AM demodulator, or for experimenting. In practice, most users will use AM mode instead. Typical bandwidth: 6–10 kHz.

## Volume, Mute, and Squelch

| Key | Action |
|---|---|
| ++page-up++ | Volume up (+5%) |
| ++page-down++ | Volume down (-5%) |
| ++f3++ | Mute / Unmute |
| ++shift+page-up++ | Squelch up (+3 dB) |
| ++shift+page-down++ | Squelch down (-3 dB) |

Volume and squelch sliders are also available in the main window. The mute toggle button is labelled "Mute (M)" in the UI.

The **squelch** silences audio when the signal drops below a threshold. This is useful for scanning or monitoring — you only hear audio when someone is transmitting. Set it just above the noise level so that only real signals open the squelch. A value of -80 dBm is a good starting point; raise it if you hear too much noise.

## Signal Information

Press ++i++ at any time to hear a spoken status report including:

- Signal strength in dBFS with S-meter reading (S0–S9+30)
- Stereo or Mono (in WFM mode)
- RDS station name (in WFM mode, when available)
- CTCSS tone frequency (in NFM mode, when detected)
- Squelch state (open or closed)
- Mute state
- Demod offset and listening frequency (when a software VFO offset is active)

## RF Settings

Open the RF Settings dialog with ++ctrl+r++ to configure hardware parameters.

### SDR Device

If you have multiple RTL-SDR dongles connected, select which one to use here. Most users will only have one device listed.

### Sample Rate

The rate at which the SDR digitises radio signals, measured in samples per second. Higher rates capture a wider slice of spectrum but require more CPU. The default of 2,400 kHz (2.4 MSPS) is a good balance — it captures ±1.2 MHz around the tuned frequency and works well on most computers. Lower rates like 1,024 kHz reduce CPU usage but narrow the visible spectrum.

### RF Gain

Controls how much the tuner amplifies the incoming signal before digitising it. When the radio is running, the dropdown shows the exact gain steps supported by your tuner hardware (e.g. 0.0 dB, 0.9 dB, 1.4 dB, ... up to 49.6 dB for the R820T tuner).

- **Too low**: weak signals disappear into the noise floor — you won't hear anything.
- **Too high**: strong signals overload the ADC, causing distortion and spurious signals that aren't really there.
- **Starting point**: 30–40 dB is usually good for FM broadcast. Lower gains (15–25 dB) work better for strong local signals. Higher gains (40+ dB) help with weak or distant signals.

When RTL AGC is enabled, the gain dropdown is disabled because gain is controlled automatically.

### PPM Correction

Compensates for the frequency error in your dongle's crystal oscillator. Most RTL-SDR dongles are off by a few parts per million (PPM), which means the displayed frequency doesn't exactly match the real frequency. A typical value is between -50 and +50 PPM. If stations seem slightly off-frequency, adjust this value until they are centred. You can calibrate using a known signal like a local FM station.

### RTL AGC

Enables the RTL2832U chip's **automatic gain control**. When turned on, the hardware adjusts gain dynamically to keep the signal level optimal. This is convenient for scanning across bands with very different signal strengths, but can introduce pumping (gain changes causing volume swings). For manual control and best results on a single frequency, leave AGC off and set the gain manually.

### Offset Tuning

Eliminates the **DC spike** — a narrow spurious signal that appears at the exact centre of the spectrum. This spike is an artefact of the direct-conversion receiver architecture and is not a real signal. Offset tuning shifts the tuner's local oscillator slightly so the spike falls outside the passband. Enable this if you see a persistent signal at the centre frequency that doesn't go away when you change gain. Some tuners or drivers may not support this feature.

### IF Bandwidth

Sets the hardware **intermediate frequency (IF) filter** bandwidth inside the R820T tuner. This is the analogue filter applied before the signal is digitised.

- **Auto** (default): AccessDR selects a suitable bandwidth based on the current demodulation mode — 300 kHz for WFM, 100 kHz for NFM/AM/SSB/CW.
- **Manual values** (250 kHz – 2 MHz): override the automatic selection. A narrower IF bandwidth rejects out-of-band interference and can improve reception of weak signals next to strong ones, but setting it too narrow will cut off the signal you are trying to receive.

In most cases, Auto is the best choice. Manual IF bandwidth is useful when you have a strong interfering signal near the frequency you are listening to.

### Direct Sampling

Lets RTL-SDR dongles receive **HF** (roughly 0.1–28 MHz — shortwave, CB at 27 MHz, AM/MW and LW broadcast) **without an upconverter**, by sampling the ADC directly and bypassing the R820T tuner.

- **Off** (default): normal tuner operation (~24 MHz and up). Use this for FM, airband, VHF/UHF, PMR446, etc.
- **Q-branch (HF)**: the usual direct-sampling input for HF on RTL-SDR Blog V3 and similar dongles.
- **I-branch**: the alternate ADC input; some dongles are wired for this instead.

**Important caveats:**

- Direct sampling is an **RTL2832U-only** feature. SDRs reached over SoapySDR (Airspy, SDRplay, etc.) tune HF natively and ignore this setting.
- It only works if your specific dongle is **wired for it** — the RTL-SDR Blog V3 has the input built in; many dongles need a hardware mod. Reception is **noisy** and benefits from a band-pass/low-pass filter.
- Changing this restarts the capture stream. Remember to switch it **back to Off** for normal VHF/UHF use.

### Noise Blanker

The noise blanker suppresses short impulse noise (electrical interference, ignition noise, power line clicks) from the raw IQ signal before demodulation. Enable it in **Options > RF Settings** (++ctrl+r++).

- **Threshold** controls sensitivity — a lower value blanks more aggressively. The default of 5.0 means any sample exceeding 5x the median signal magnitude is treated as an impulse. Raise the threshold if the blanker clips normal signal peaks; lower it if impulse noise persists.
- Blanked samples are replaced by linear interpolation from neighbouring clean samples, avoiding the clicks that hard zeroing would produce.

### Bias Tee

The Bias Tee option supplies **4.5 V DC power** through the coaxial antenna connector. This is used to power external low-noise amplifiers (LNAs), active antennas, or bias-T powered filters directly from the SDR dongle — no separate power supply needed.

**Supported devices:** RTL-SDR Blog V3 and other dongles with built-in bias-T circuitry. The NESDR SMArt V5 also supports bias-T.

**WARNING:** Enabling Bias Tee on a device or antenna that does not support it can cause **permanent hardware damage**. A passive antenna may be shorted by the DC voltage. Only enable this if you know your entire signal chain (dongle, cables, antenna/LNA) is designed for bias-T power.

**When to use:**

- Powering an LNA mounted at the antenna (e.g. LNA4ALL, Nooelec SAWbird)
- Powering an active GPS, ADS-B, or L-band antenna
- Powering a bias-T fed bandpass filter

A confirmation dialog will appear each time you enable this setting to prevent accidental activation.

## WFM Settings

Open the WFM Settings dialog with ++ctrl+w++ to configure broadcast FM-specific parameters. Changes take effect immediately if you are currently receiving in WFM mode.

See the [WFM mode description](#wfm--wideband-fm) above for details on each setting.

## Spectrum

The spectrum display shows signal power across the SDR's bandwidth. AccessDR provides multiple ways to explore the spectrum: sonification sweeps, an interactive cursor with probe tone, zoom, and peak detection. All spectrum features work on paused (frozen) data as well as live data.

### Shortcuts

| Key | Action |
|---|---|
| ++f++ | Speak top spectrum peaks |
| ++g++ | Describe current spectrum range |
| ++=++ / ++plus++ | Zoom in (halve span) |
| ++-++ | Zoom out (double span) |
| ++backspace++ | Reset zoom to full spectrum |
| ++f5++ | Sonification snapshot sweep |
| ++ctrl+f5++ | Toggle continuous sweep |
| ++ctrl++ (hold) | Play probe tone at cursor |
| ++ctrl+left++ / ++ctrl+right++ | Move cursor while probing |
| ++left++ / ++right++ | Step cursor and announce position |
| ++t++ | Speak cursor frequency, power, and S-meter reading |
| ++c++ | Reset cursor to centre, clear demod offset |
| ++ctrl+t++ | Tune LO to cursor frequency, clear offset |
| ++shift+c++ | Toggle "demod follows cursor" mode |

### Waterfall Display

Below the line graph, a **waterfall** (spectrogram) scrolls vertically with the newest data at the top. Each horizontal line represents one FFT snapshot, with colour encoding signal power — brighter colours mean stronger signals. This makes it easy to spot intermittent transmissions, drifting signals, and patterns over time.

The waterfall uses colour-vision-deficiency-safe colour schemes. Open **Options > Spectrum Settings** (++ctrl+s++) to choose between:

- **Viridis** — perceptually uniform with monotonic luminance, safe for all forms of colour blindness
- **Magma** — high-contrast dark-to-bright scheme
- **Grayscale** — pure black-to-white, universally accessible

Adjust the **dB floor** (brightness) and **dB ceiling** (contrast) to control which signals are visible. A lower floor reveals weaker signals; a narrower range between floor and ceiling increases contrast.

### Sonification

Sonification converts the FFT spectrum into audio, letting you "hear" the spectrum:

- The spectrum is swept from left to right using **stereo panning** — left ear = low end, right ear = high end
- **Pitch** encodes signal power — stronger signals produce a higher pitch, weak signals a low pitch
- Signals below the noise floor are silent, so only real signals are audible

Press ++f5++ for a **snapshot sweep** — a single left-to-right pass. Press ++ctrl+f5++ to toggle **continuous sweep** — repeats until you press ++ctrl+f5++ again. Sonification activates automatically when you start a sweep.

### Zoom

Zoom narrows the visible and sonified range so closely-spaced signals are easier to distinguish. Press ++=++ to zoom in, ++-++ to zoom out, and ++backspace++ to reset. Press ++g++ to hear the current range.

Zoom levels: 1x (full) → 2x → 4x → 8x → 16x → 32x. At 2.4 MSPS, 32x zoom gives a ~75 kHz span — still useful for NFM or AM signals.

The visual spectrum panel always shows the full bandwidth, with yellow dashed lines marking the zoom boundaries and dimmed regions outside the zoom.

### Cursor and Probe Tone

The spectrum cursor lets you explore specific points in the spectrum interactively.

**Probe tone:** Hold ++ctrl++ to hear a continuous tone at the cursor's position. Pitch encodes signal power (same mapping as sweep sonification) and stereo pan encodes frequency position (left = low, right = high). While Ctrl is held, press ++left++ / ++right++ to move through the spectrum. Release the arrows to stop moving — the tone continues. Release Ctrl to stop the tone entirely.

**Stepping:** Press ++left++ / ++right++ without Ctrl to step the cursor one position and hear the frequency, power, and S-meter reading announced via speech. Press ++t++ to re-announce the current cursor position at any time.

**Peaks:** Press ++f++ to hear the top spectrum peaks announced as frequency and power level. The number of peaks reported is configurable in the Spectrum Settings dialog (++ctrl+s++).

You can also click on the spectrum panel with the mouse to jump the cursor to that position. The cursor respects zoom — when zoomed in, the range narrows to the visible spectrum.

### Software VFO Offset

By default, the demodulator processes the signal at the hardware LO (centre frequency). Press ++shift+c++ to enable **"demod follows cursor"** mode — moving the cursor also shifts the demodulator to listen at the cursor's frequency. This works like clicking on a waterfall in HDSDR or SDR++ to move a software VFO.

The offset is applied by a software mixer in the DSP chain. The hardware LO does not move, so the full spectrum remains visible and the probe tone works normally.

Press ++c++ to reset the cursor and offset to centre. Press ++ctrl+t++ to retune the hardware LO to the cursor and clear the offset. The offset is clamped to ±120 kHz (half the baseband rate). A yellow dashed "D" marker appears on the spectrum panel to show where the demodulator is listening. Press ++i++ to hear the current offset and listening frequency.

### Sonification Settings

Open the Spectrum Settings dialog with ++ctrl+s++ to adjust:

- **Weak signal pitch** — the pitch for signals at the noise floor (default 200 Hz)
- **Strong signal pitch** — the pitch for the strongest signals (default 4000 Hz)
- **Sweep speed** — how long one full left-to-right sweep takes (default 5 seconds; slower speeds give more time to distinguish closely-spaced signals)

## Scanner

The scanner automatically steps through a frequency range, pausing on active signals.

1. Open the Scanner dialog with ++ctrl+n++
2. Set the start frequency, stop frequency, and step size
3. Set the squelch threshold — signals above this level will be flagged
4. Start the scan

### Scanner Controls

| Key | Action |
|---|---|
| ++h++ | Hold on the current frequency (toggle) |
| ++k++ | Skip to the next frequency |
| ++escape++ | Stop the scan |

When a signal is found, the scanner pauses briefly so you can listen, then continues.

## Remote SDR (rtl_tcp)

AccessDR can receive IQ data from a remote `rtl_tcp` server instead of a locally connected USB dongle. This is useful when the antenna and SDR dongle are in a different location — for example a Raspberry Pi on the roof running `rtl_tcp`, streaming data to your PC over the network.

### Setting Up a Remote Server

On the remote machine (e.g. Raspberry Pi), start `rtl_tcp`:

```bash
rtl_tcp -a 0.0.0.0
```

This listens on port 1234 by default. Use `-p` to change the port.

### Managing Servers

Open the Remote SDR Servers dialog with ++ctrl+g++ to manage your server list:

- **Add** — enter a name (e.g. "Roof Pi"), host address (IP or hostname), and port
- **Edit** — modify the name, host, or port of a selected server
- **Remove** — delete a selected server from the list
- **Test Connection** — verify that the server is reachable and responding with a valid rtl_tcp handshake

Changes are saved immediately on each action. You can configure zero or more servers.

### Selecting a Remote Server

Configured servers appear in the RF Settings device dropdown (++ctrl+r++) alongside local USB devices. Select a remote server to switch to it — the radio will restart using the rtl_tcp backend. Select a local device to switch back.

When receiving from a remote server, the status bar shows the server name and the spoken status (++i++) includes the remote connection info.

### Limitations

- **Latency** — network latency adds delay to the audio. A local network (LAN or Wi-Fi) works well; a slow internet connection may cause dropouts.
- **Bandwidth** — rtl_tcp streams raw IQ data at the full sample rate. At 2.4 MSPS, this is about 4.8 MB/s (38 Mbit/s). Ensure your network can handle this.
- **Single client** — a standard rtl_tcp server supports one client at a time.

## Bookmarks

Save and recall favourite frequencies:

1. Open the Bookmarks dialog with ++ctrl+b++
2. **Save** the current frequency and mode as a bookmark
3. **Load** a bookmark to tune to it instantly

Bookmarks are stored in a JSON file and persist across sessions.
