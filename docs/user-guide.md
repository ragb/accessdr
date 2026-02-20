# User Guide

## Tuning

### Frequency Entry

Press ++q++ to open the frequency entry dialog. You can also click the frequency display or the "..." button next to it.

Enter a frequency in one of these formats:

- **MHz** (most common): `98.1` or `98.1 MHz`
- **kHz**: values between 30,000 and 30,000,000 are treated as kHz
- **Hz**: values above 30,000,000 are treated as Hz

Press ++enter++ to confirm or ++escape++ to cancel.

### Step Tuning

Use ++up++ and ++down++ to tune by the current step size. Hold ++ctrl++ to tune by 10x the step size.

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

### Frequency History

AccessDR keeps a history of the last 50 frequencies you tuned to. Use ++alt+left++ to go back and ++alt+right++ to go forward, similar to a web browser.

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

| Key | Mode | Description |
|---|---|---|
| ++m++ ++w++ | WFM | Wideband FM — for broadcast radio. Automatically detects stereo. |
| ++m++ ++n++ | NFM | Narrowband FM — for two-way radio, amateur, PMR, etc. |
| ++m++ ++a++ | AM | Amplitude modulation — for air band, AM broadcast, shortwave. |
| ++m++ ++u++ | USB | Upper sideband — for amateur HF above 10 MHz. |
| ++m++ ++l++ | LSB | Lower sideband — for amateur HF below 10 MHz. |
| ++m++ ++c++ | CW | Continuous wave — for Morse code, with narrow filter. |
| ++m++ ++d++ | DSB | Double sideband — full carrier AM without filtering. |

Each mode has selectable filter bandwidths. Open the main window's BW dropdown or the RF Settings dialog (++ctrl+r++) to adjust.

## RF Settings

Open the RF Settings dialog with ++ctrl+r++ to configure hardware parameters:

- **RF Gain** — when the radio is running, shows the actual valid gain steps for your tuner (e.g. 0.0, 0.9, ... 49.6 dB for R820T)
- **RTL AGC** — enables the RTL2832U's digital automatic gain control
- **Offset Tuning** — eliminates the DC spike at the centre frequency by offsetting the tuner's LO
- **IF Bandwidth** — sets the hardware IF filter bandwidth (Auto, 250 kHz, 500 kHz, 1 MHz, 1.5 MHz, 2 MHz). Narrower bandwidths improve selectivity at the cost of bandwidth

## Signal Information

Press ++i++ at any time to hear a spoken status report including:

- Signal strength in dBFS with S-meter reading (S0–S9+30)
- Stereo or Mono (in WFM mode)
- Squelch state (open or closed)
- Mute state

## Spectrum and Sonification

Sonification converts the FFT spectrum into audio, letting you "see" the spectrum with your ears.

### How It Works

- The spectrum is swept from left to right using **stereo panning** — left ear = low end, right ear = high end
- **Pitch** encodes signal power — stronger signals produce a higher pitch, weak signals a low pitch
- Signals below the noise floor are silent, so only real signals are audible
- Strong signals pop out as clearly audible high-pitched tones at their position in the stereo field

### Using Sonification

1. Open the Spectrum & Sonification dialog with ++ctrl+s++
2. Enable sonification with the checkbox
3. Choose between **Continuous sweep** or **Snapshot** mode
4. Press ++space++ in the main window for a one-shot snapshot sweep

### Sonification Settings

- **Weak/Strong signal pitch** — pitch range mapped to signal power (default 200-4000 Hz)
- **Sweep speed** — how long one full L-to-R sweep takes (default 5 seconds)

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
