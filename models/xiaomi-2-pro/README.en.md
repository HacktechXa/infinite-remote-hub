# Xiaomi Bluetooth Remote 2 Pro

Model ID: `xiaomi-2-pro`. HID vendor `0x2717`, product `0x32B8`. Package format v2, release `1.0.0`.

Pair in macOS Bluetooth settings, grant Input Monitoring, and grant Accessibility for simulated shortcuts. Select the device and verify press/release events in diagnostics. Diagnostics suspend the app’s own actions. Set ChatGPT’s dictation shortcut to F5 for the voice key. The app does not capture the remote microphone’s audio or integrate the factory NFC tag. HID monitoring is non-exclusive.

Install this model from the resource library, or choose its ZIP in “Import model package…”. Folder import is also supported. The app starts without bundled remote models. A higher release from the same source can update an installation; another source cannot replace it. Model updates preserve user mappings.

Defaults: power toggles displays (hold locks); voice triggers dictation; arrows and confirm send arrow keys and Return; back sends Esc; home brings the default target application forward (initially Codex); volume adjusts system volume; menu opens running apps; TV opens the media app chooser. Actions are customizable in the app.
