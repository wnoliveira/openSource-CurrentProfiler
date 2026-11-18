# Validation record

Software and firmware version: **1.0.0**. Both remain **in development**.

Automated checks verify parts of the data path and the interface. They cannot establish electrical accuracy, pulse response or reliable delivery on a particular ESP32, sensor, cable and computer. The distinction matters when using this project in an experiment or publication.

## Current revision

The current desktop source includes dark/system-language defaults, full-screen startup, themed About/Licenses dialogs, mouse trigger selection and preference persistence. The following checks passed on **18 November 2026** using the Windows Python 3.12 x64 environment:

| Check | Result |
|---|---|
| Core Python suite | 8 tests passed. The C-planner comparison class was skipped because a host GCC compiler was not available in this Python test environment. |
| Desktop suite | 29 tests passed, including full-screen startup/shortcuts, dialog colors, language-selector width, preference restoration from disk, pending sensor settings after reconnection and real Qt mouse clicks/drags on the trigger markers. |
| Dependency consistency | `pip check` reported no broken requirements. |
| GUI acquisition/export QA | 1005 simulated capture samples, 500 screen-export samples, 1000.0 Hz from simulated timestamps, and a 70579-byte plot PNG. |
| Source application's self-test | Passed on 64-bit Python: 58 captured samples and 73 screen-export samples, including English/Portuguese, Qt dialog translations, serial-port enumeration, SVG, notices, DEMO, themes and CSV/JSON/PNG output. |
| Updated Windows single-file build | Built in `desktop/dist/updated/IoTCurrentScope.exe` because the existing top-level executable could not be opened for replacement. The frozen 64-bit executable passed its self-test in an isolated working directory: 58 captured samples, 73 screen-export samples and a 50522-byte PNG. The corresponding source archive and `self-test.json` are in the same directory. |
| Previous Windows single-file build | Built successfully before the latest desktop UI changes and tested as a frozen 64-bit executable in an isolated working directory: 52 captured samples, 48 screen-export samples and a 49160-byte PNG. The packaged check also passed English/Portuguese, Qt dialog translations, serial ports, SVG, notices, DEMO, themes and CSV/JSON output. |
| Windows bundle inventory | Qt Core, Gui, Network, OpenGL, OpenGLWidgets, Svg, Test and Widgets DLLs were found, with `qtbase_pt_BR.qm`. No Virtual Keyboard component was found. |

The refreshed GUI results are in `validation/qa_report.json`; the source self-test is `validation/python_self_test.json`. The updated executable's check is copied to `validation/windows_ui_self_test.json`. The previous packaged check and its bundled-file inventory remain in `validation/windows_self_test.json` and `validation/windows_bundle.json`. Demonstration CSVs, sidecars and screenshots were refreshed from the English interface before the latest UI update. The desktop suite was also repeated with actual Windows font metrics after correcting offscreen font discovery. These remain simulated data. Counts describe those particular runs and can vary with test scheduling.

From the repository root, with the desktop environment installed:

```powershell
.\desktop\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\desktop\.venv\Scripts\python.exe -m unittest discover -s desktop/tests -v
```

The C planning comparison requires a supported host compiler. It is not an ESP-IDF build. The GUI checks run with simulated data, and a passing DEMO test says nothing about the INA219's electrical performance.

The current firmware was built successfully on **18 November 2026** with the installed **ESP-IDF 6.1 / Xtensa GCC 15.2** toolchain. The application image is **190896 bytes**. Project C files compiled without warnings; SDK configuration/ownership/debugger notices were nonfatal. The compatibility-build outputs are in the ignored `firmware/build/review-idf61` directory. The historical reference is ESP-IDF 5.4.2; that version was not rebuilt during this review.

No current-source image has been flashed or tested on the ESP32. Flash a fresh build before the bench tests below. The existing `firmware/prebuilt` files and hashes still describe an earlier build.

## Reports retained from the original package

The reports below record earlier work. They are retained as historical evidence and must be distinguished from the refreshed Python/GUI results above.

| Report | What it records |
|---|---|
| `firmware_build.json` | ESP-IDF 5.4.2, ESP32 target, successful build and link, 254384-byte application. Explicitly says hardware was not tested. |
| `serial_pty_report.json` | Linux pseudo-terminal reception: 1083 accepted samples, two missing samples and one CRC error after one removed and one corrupted line. |
| `onefile_build.json` | A historical Linux x86_64 single-file build and DEMO startup; its statement that Windows was not built applies to that earlier run. A current Windows build is recorded above. |

The original package described protocol/CRC, sequence gaps and rollover, current conversion, all integer rates, trigger modes, calibration and CSV/PNG export checks. The relevant source tests are retained so they can be run again. Their previous success does not imply that the complete present revision has been exercised on hardware.

Pinned desktop dependencies are PySide6 6.8.3, pyqtgraph 0.13.7, NumPy 2.2.6 and pySerial 3.5, with Python 3.12 x64 as the reference interpreter. The Windows build uses PyInstaller 6.13.0. A packaged self-test report describes only the executable that produced it.

## What still needs the bench

The project has not established an uncertainty budget or validated current accuracy against a traceable reference. Before relying on a result, check sign, actual resistance, load voltage drop, offset, gain, temperature sensitivity and performance throughout the intended range.

A requested rate of 1000 Hz is a scheduling target. Delivered rate, timing variation, I²C failures and serial losses must be observed on the hardware and computer being used. The CP2102/driver combination must sustain 460800 baud. Longer averaging can make a trace quieter while hiding short events; a quieter trace alone is not evidence of better accuracy.

The current Windows executable passed its packaged DEMO test and its Qt inventory was inspected. USB driver behavior, physical serial communication and operation on the intended user's computer still need testing. A Linux packaging report cannot establish those results. Review release notices and source availability separately from functional tests; see [THIRD_PARTY.md](THIRD_PARTY.md).

## First hardware session

1. With no load connected, power the logger, connect the desktop and confirm the expected INA219 address. Run zero calibration for every PGA range that will be used.
2. Apply known steady currents at several points in the selected range. Compare for at least one minute per point, recording the reference instrument, shunt value and temperature. Check that positive current has the intended sign.
3. Run at 1000 Hz for ten minutes. Record received and missing samples, CRC errors, I²C errors, skipped periods, transmission drops and maximum start delay. Do not add firmware counters to the PC missing total.
4. Repeat at 500, 100 and 10 Hz with a steady load. Compare mean and standard deviation. Use the known input and reference reading to distinguish reduced noise from a change in accuracy.
5. Apply pulses of known duration and compare amplitude, width and integral with a reference of adequate bandwidth. Check whether averaging and unobserved intervals miss events relevant to the experiment.
6. Run for more than 72 minutes to exercise timestamp rollover with physical hardware.
7. Disconnect and reconnect. Confirm capture closure, check whether firmware acquisition is still running, stop it if needed and start a new session before recording again.

For a publication, retain the code revision, firmware build, settings sidecars, raw CSV, reference readings and environmental conditions. Report observed limitations alongside the results; an absence of error messages does not establish a known measurement uncertainty.
