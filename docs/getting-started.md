# Getting Started

## Requirements

- **Operating System:** Windows 10 or 11
- **Hardware:** Any RTL2832U-based SDR dongle (e.g. NESDR SMArt, RTL-SDR Blog V3/V4, generic RTL-SDR)
- **Screen reader:** NVDA, JAWS, or Windows Narrator (optional but recommended)

## Hardware Setup

### Connecting the dongle

1. Connect your RTL-SDR dongle to a USB port
2. Attach an antenna to the dongle's SMA connector — even a short whip antenna will pick up local FM stations

### Driver Setup

RTL-SDR dongles need the **WinUSB** driver instead of the default Windows driver. If you've used SDR# or similar software before, this is likely already done.

To install or check the driver:

1. Download [Zadig](https://zadig.akeo.ie/)
2. Run Zadig as administrator
3. From the menu, select **Options > List All Devices**
4. Select your RTL-SDR device from the dropdown (usually called "Bulk-In, Interface (Interface 0)")
5. Set the driver to **WinUSB** and click **Replace Driver**

!!! note
    You only need to do this once. The driver persists across reboots.

## Installation

### Windows Installer

Download the latest installer from the [Releases page](https://github.com/ragb/accessdr/releases/latest) and run it. The installer does not require administrator privileges.

After installation, launch AccessDR from the Start menu or desktop shortcut.

### Running from Source

If you prefer to run from source or want to contribute:

```bash
git clone https://github.com/ragb/accessdr.git
cd accessdr
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
invoke fetch-dlls
python main.py
```

The `invoke fetch-dlls` command downloads the RTL-SDR library automatically.

## First Steps

1. **Start the radio** — press ++r++ or click the Start button. AccessDR will announce "Radio started" through your screen reader.
2. **Tune to a station** — press ++up++ or ++down++ to step through frequencies. The current frequency is announced after each step.
3. **Change the step size** — press ++s++ to cycle through step sizes (1 Hz to 1 MHz). Use 100 kHz steps for quickly scanning FM broadcast.
4. **Switch modes** — press ++w++ for Wide FM (broadcast radio), ++n++ for Narrow FM, ++a++ for AM, etc.
5. **Check signal strength** — press ++i++ to hear the current signal level and status.
6. **Adjust volume** — use the Volume slider or press ++m++ to mute/unmute.

See the full [User Guide](user-guide.md) for detailed instructions on all features.
