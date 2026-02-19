# User Guide

## Tuning

### Frequency Entry

You can type a frequency directly into the frequency field:

- **MHz** (most common): `98.1` or `98.1 MHz`
- **kHz**: values between 30,000 and 30,000,000 are treated as kHz
- **Hz**: values above 30,000,000 are treated as Hz

Press ++enter++ to tune to the entered frequency.

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

Switch modes with a single key press:

| Key | Mode | Description |
|---|---|---|
| ++w++ | WFM | Wideband FM — for broadcast radio. Automatically detects stereo. |
| ++n++ | NFM | Narrowband FM — for two-way radio, amateur, PMR, etc. |
| ++a++ | AM | Amplitude modulation — for air band, AM broadcast, shortwave. |
| ++u++ | USB | Upper sideband — for amateur HF above 10 MHz. |
| ++l++ | LSB | Lower sideband — for amateur HF below 10 MHz. |
| ++c++ | CW | Continuous wave — for Morse code, with narrow filter. |
| ++d++ | DSB | Double sideband — full carrier AM without filtering. |

Each mode has selectable filter bandwidths. Open the main window's BW dropdown or the RF Settings dialog (++ctrl+r++) to adjust.

## Signal Information

Press ++i++ at any time to hear a spoken status report including:

- Signal strength in dBFS with a quality rating (Excellent / Good / Fair / Weak / None)
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
