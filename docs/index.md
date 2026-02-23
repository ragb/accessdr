# AccessDR

!!! warning "Alpha Software"
    AccessDR is a proof of concept in a very early alpha stage. Expect rough edges, missing features, and breaking changes.

**AccessDR** is an accessible software-defined radio (SDR) application designed for blind and visually impaired users. It brings the world of radio monitoring to screen reader users with full keyboard navigation, spoken feedback, and spectrum sonification.

## What is SDR?

Software-defined radio uses a small USB dongle to receive radio signals across a wide range of frequencies. Instead of a traditional hardware radio with a fixed tuner, SDR does all the signal processing in software — giving you access to FM broadcast, air traffic control, amateur radio, weather stations, and much more from a single device.

## Key Features

- **Screen reader support** — every control, status change, and signal reading is spoken through your screen reader (NVDA, JAWS, Narrator)
- **7 demodulation modes** — WFM (stereo, RDS, hi-blend), NFM (CTCSS detection), AM, USB, LSB, CW, DSB
- **RDS decoding** — automatic station name, radio text, and program type for FM broadcast
- **CTCSS tone detection** — identifies sub-audible access tones on NFM channels
- **Noise blanker** — suppresses impulse noise from electrical interference
- **Waterfall display** — real-time spectrogram with CVD-safe colour schemes (Viridis, Magma, Grayscale) for spotting intermittent signals and drift
- **Spectrum sonification** — hear the RF spectrum as a sweeping tone that maps signal strength to volume and frequency position to pitch
- **Remote SDR (rtl_tcp)** — stream IQ data from a remote rtl_tcp server over the network, with multi-server management
- **Frequency scanner** — automatically scan a range and stop on active signals
- **Bookmarks** — save and recall your favourite frequencies
- **Band presets** — jump to common bands (FM, Air, Amateur, Weather, Marine) with a single menu selection

## Quick Start

1. Plug in your RTL-SDR dongle
2. Install the [WinUSB driver](getting-started.md#driver-setup) if you haven't already
3. [Download the installer](https://github.com/ragb/accessdr/releases/latest) or [run from source](getting-started.md#running-from-source)
4. Press ++r++ to start the radio
5. Use ++up++ / ++down++ to tune

See the [Getting Started](getting-started.md) guide for detailed setup instructions.

## Links

- [GitHub Repository](https://github.com/ragb/accessdr)
- [Latest Release](https://github.com/ragb/accessdr/releases/latest)

## About

AccessDR is created by [Rui Batista](https://github.com/ragb) and released under the [MIT License](https://github.com/ragb/accessdr/blob/master/LICENSE).
