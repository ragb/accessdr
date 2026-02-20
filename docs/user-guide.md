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

### NFM — Narrowband FM

Used by most **two-way radio** systems: amateur (ham) radio repeaters, PMR446 walkie-talkies, marine VHF, NOAA weather radio, taxi and business radios, and public safety communications. NFM channels are much narrower than broadcast FM (12.5 or 25 kHz), so you will hear a single voice conversation rather than a music station. Set the step size to 12.5 or 25 kHz when scanning for NFM signals.

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

## Signal Information

Press ++i++ at any time to hear a spoken status report including:

- Signal strength in dBFS with S-meter reading (S0–S9+30)
- Stereo or Mono (in WFM mode)
- Squelch state (open or closed)
- Mute state
- Demod offset and listening frequency (when a software VFO offset is active)

## Spectrum and Sonification

Sonification converts the FFT spectrum into audio, letting you "see" the spectrum with your ears.

### How It Works

- The spectrum is swept from left to right using **stereo panning** — left ear = low end, right ear = high end
- **Pitch** encodes signal power — stronger signals produce a higher pitch, weak signals a low pitch
- Signals below the noise floor are silent, so only real signals are audible
- Strong signals pop out as clearly audible high-pitched tones at their position in the stereo field

### Using Sonification

- Press ++f5++ for a **snapshot sweep** — a single left-to-right pass, then stops
- Press ++ctrl+f5++ to toggle **continuous sweep** — repeats until you press ++ctrl+f5++ again

No need to enable sonification separately — it activates automatically when you start a sweep.

### Sonification Settings

Open the Spectrum Settings dialog with ++ctrl+s++ to adjust:

- **Weak signal pitch** — the pitch for signals at the noise floor (default 200 Hz)
- **Strong signal pitch** — the pitch for the strongest signals (default 4000 Hz)
- **Sweep speed** — how long one full left-to-right sweep takes (default 5 seconds; slower speeds give more time to distinguish closely-spaced signals)

### Spectrum Zoom

By default sonification sweeps the entire SDR bandwidth (typically ±1.2 MHz around the tuned frequency). Zoom narrows the sonified range so closely-spaced signals get more sweep time and are easier to distinguish.

| Key | Action |
|---|---|
| ++=++ or ++plus++ | Zoom in (halve the span) |
| ++-++ | Zoom out (double the span) |
| ++backspace++ | Reset to full spectrum |
| ++g++ | Describe current spectrum range |

Zoom levels: 1x (full) → 2x → 4x → 8x → 16x → 32x. At 2.4 MSPS, 32x zoom gives a ~75 kHz span — still useful for NFM or AM signals.

The visual spectrum panel always shows the full bandwidth, with yellow dashed lines marking the zoom boundaries and dimmed regions outside the zoom.

Zoom is session-only and resets when you restart the app.

### Spectrum Cursor

The spectrum cursor lets you interactively explore specific points in the spectrum. Think of it as clicking on a waterfall display — you move a cursor through the spectrum and hear a tone that represents the signal at that point.

#### Using the Cursor

Hold ++ctrl++ to hear a continuous probe tone at the cursor's current position:

- **Pitch** encodes signal power at the cursor position — same mapping as sweep sonification
- **Stereo pan** encodes frequency position — left ear = low end, right ear = high end

While Ctrl is held, press ++left++ or ++right++ to move the cursor through the spectrum. The cursor moves at a configurable speed (default: 30% of visible spectrum per second). Release the arrow keys to stop moving — the tone continues playing at the current position. Release Ctrl to stop the tone.

Use ++left++ / ++right++ without Ctrl to step the cursor and hear the position announced via speech.

| Key | Action |
|---|---|
| ++ctrl++ (hold) | Play probe tone at cursor |
| ++ctrl+left++ / ++ctrl+right++ | Move cursor while probing |
| ++left++ / ++right++ | Step cursor and announce position |
| ++t++ | Speak cursor frequency, power, and S-meter reading |
| ++c++ | Reset cursor to centre, clear demod offset |
| ++ctrl+t++ | Tune LO to cursor frequency, clear offset |
| ++shift+c++ | Toggle "demod follows cursor" mode |

You can also click on the spectrum panel with the mouse to jump the cursor to that position.

The cursor respects zoom — when zoomed in, the cursor range narrows to the visible portion of the spectrum.

#### Software VFO Offset (Demod Follows Cursor)

By default, the demodulator always processes the signal at the hardware LO (centre frequency). Press ++shift+c++ to enable **"demod follows cursor"** mode — when enabled, moving the cursor with Left/Right arrows or Ctrl+arrows also shifts the demodulator to listen at the cursor's frequency. This works like clicking on a waterfall in HDSDR or SDR++ to move a software VFO.

The offset is applied by a software mixer in the DSP chain that shifts the selected signal down to DC for demodulation. The hardware LO does not move, so the full spectrum remains visible and the probe tone continues to work normally.

- **Shift+C** — toggle follow mode on/off (announced via speech)
- **Left/Right** — step cursor; when follow mode is on, audio shifts to the new position
- **Ctrl+hold arrows** — probe and move cursor; when follow mode is on, audio follows
- **C** — reset cursor to centre and clear the offset (audio returns to centre frequency)
- **Ctrl+T** — retune the hardware LO to the cursor frequency and clear the offset
- **Up/Down** — tune the LO by step; the offset is preserved, so the listening frequency shifts with the LO
- **Ctrl+Q** (enter LO frequency) — sets the LO directly and clears the offset
- **Ctrl+O** (enter listening frequency) — sets the demod offset so the listening frequency matches

The offset is clamped to ±120 kHz (half the baseband rate). A yellow dashed "D" marker appears on the spectrum panel to show where the demodulator is listening. Press ++i++ to hear the current offset and listening frequency in the status report.

### Spectrum Peaks

Press ++f++ to hear the top spectrum peaks announced as frequency and power level. The number of peaks reported is configurable in settings.

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

## Bookmarks

Save and recall favourite frequencies:

1. Open the Bookmarks dialog with ++ctrl+b++
2. **Save** the current frequency and mode as a bookmark
3. **Load** a bookmark to tune to it instantly

Bookmarks are stored in a JSON file and persist across sessions.

## Squelch

The squelch control silences audio output when the signal drops below a threshold. This is useful for scanning or monitoring — you only hear audio when someone is transmitting.

- Adjust the squelch slider in the main window
- Set it just above the noise level so that only real signals open the squelch
- A value of -80 dBm is a good starting point; raise it if you hear too much noise

Press ++i++ to check whether the squelch is currently open or closed.
