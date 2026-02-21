# Keyboard Shortcuts

## Radio Controls

| Key | Action |
|---|---|
| ++f2++ | Start / Stop radio |
| ++space++ | Pause / Resume radio |
| ++f3++ | Mute / Unmute |
| ++i++ | Read signal strength, stereo/mono, RDS, CTCSS, squelch state |

## Tuning

| Key | Action |
|---|---|
| ++q++ | Report LO (tuned) frequency |
| ++o++ | Report listening (demod) frequency |
| ++ctrl+q++ | Enter LO frequency (opens dialog) |
| ++ctrl+o++ | Enter listening frequency (opens dialog) |
| ++up++ | Tune up by step |
| ++down++ | Tune down by step |
| ++shift+up++ | Tune up by 10x step |
| ++shift+down++ | Tune down by 10x step |
| ++s++ | Cycle tuning step size |

## Volume and Squelch

| Key | Action |
|---|---|
| ++page-up++ | Volume up (+5%) |
| ++page-down++ | Volume down (-5%) |
| ++shift+page-up++ | Squelch up (+3 dB) |
| ++shift+page-down++ | Squelch down (-3 dB) |

## Demodulation Modes

Press ++m++ first, then the mode letter:

| Key | Mode |
|---|---|
| ++m++ ++w++ | Wide FM (broadcast) |
| ++m++ ++n++ | Narrow FM |
| ++m++ ++a++ | AM |
| ++m++ ++u++ | USB (Upper Sideband) |
| ++m++ ++l++ | LSB (Lower Sideband) |
| ++m++ ++c++ | CW (Morse) |
| ++m++ ++d++ | DSB (Double Sideband) |

## Spectrum

| Key | Action |
|---|---|
| ++f++ | Speak top spectrum peaks |
| ++g++ | Describe current spectrum range |
| ++=++ / ++plus++ | Zoom in (halve span) |
| ++-++ | Zoom out (double span) |
| ++backspace++ | Reset zoom to full spectrum |
| ++f5++ | Sonification snapshot sweep |
| ++ctrl+f5++ | Toggle continuous sweep |

## Spectrum Cursor

| Key | Action |
|---|---|
| ++ctrl++ (hold) | Play probe tone at cursor position |
| ++ctrl+left++ / ++ctrl+right++ | Move cursor while probing |
| ++left++ | Step cursor left and announce |
| ++right++ | Step cursor right and announce |
| ++t++ | Speak cursor frequency and power |
| ++c++ | Reset cursor to centre, clear demod offset |
| ++ctrl+t++ | Tune LO to cursor frequency, clear offset |
| ++shift+c++ | Toggle "demod follows cursor" mode |

Hold Ctrl to hear a continuous probe tone at the cursor's position — pitch indicates signal power, stereo pan indicates frequency position. While Ctrl is held, press Left/Right arrows to move the cursor through the spectrum. Release the arrows to stop moving (tone continues). Release Ctrl to stop the tone. Use Left/Right without Ctrl to step the cursor silently and hear the position announced.

When "demod follows cursor" is enabled (Shift+C), moving the cursor with Left/Right or Ctrl+arrows also shifts the demodulator to listen at the cursor's frequency via a software VFO offset. Press C to reset the cursor and offset to centre. Press Ctrl+T to retune the hardware LO to the cursor and clear the offset.

## Dialogs

| Key | Dialog |
|---|---|
| ++ctrl+r++ | RF Settings (gain, PPM, sample rate) |
| ++ctrl+s++ | Spectrum Settings |
| ++ctrl+n++ | Scanner |
| ++ctrl+b++ | Bookmarks |
| ++ctrl+d++ | Audio Settings (device, buffer size) |
| ++ctrl+w++ | WFM Settings (de-emphasis, stereo, hi-blend, RDS) |
| ++f1++ | Keyboard Shortcuts help |

## Scanner (when open)

| Key | Action |
|---|---|
| ++h++ | Hold on current frequency |
| ++k++ | Skip to next frequency |
| ++escape++ | Stop scan |

## General

| Key | Action |
|---|---|
| ++alt+r++ | Open Radio menu (band presets) |
| ++ctrl+shift+b++ | Save bookmark |
| ++alt+f4++ | Quit |
