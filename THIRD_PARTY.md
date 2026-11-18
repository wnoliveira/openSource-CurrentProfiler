# Licenses and third-party components

Review date: **18 November 2026**. This review covers the source tree, pinned dependencies and packaging recipe. It does not certify an uninspected release binary.

## Project license

The repository's existing [LICENSE](LICENSE) is **GNU GPL version 3**. The desktop license copy and project documentation now agree with it. The earlier desktop draft contained an MIT notice and the firmware header also said MIT; these conflicted with the repository's tracked license. The original desktop notice is preserved at [PROJECT-ORIGINAL-MIT.txt](desktop/licenses/PROJECT-ORIGINAL-MIT.txt). Existing permission grants for material received under that notice are not withdrawn.

The current project is distributed under GPLv3. A distributed executable needs corresponding source under the applicable GPL terms; an online distribution can provide equivalent source access alongside the binary. Preserve copyright and license notices, identify modifications, and include the license. See [GPLv3 sections 4–6](https://doc.qt.io/qt-6.8/gpl.html). Running or privately modifying the project does not itself require publishing changes.

## Dependency compatibility

The principal licenses below can be used in this GPLv3 project while retaining their original notices and terms. This is a compatibility finding about the listed components, not a conclusion that every possible build is ready for public distribution.

| Component | Version used by the project | License and source |
|---|---|---|
| ESP-IDF | 5.4.2 | Apache-2.0 for Espressif code, with separately licensed components; [copyright guide](https://docs.espressif.com/projects/esp-idf/en/v5.4.2/esp32/COPYRIGHT.html). |
| Python | 3.12 x64 | PSF license and incorporated-code notices; [Python license](https://docs.python.org/3.12/license.html). |
| PySide6 / Shiboken / Qt | 6.8.3 | LGPLv3/GPLv3 or commercial, depending on component and chosen terms; [Qt for Python](https://doc.qt.io/qtforpython-6.8/). |
| pyqtgraph | 0.13.7 | MIT; [versioned license](https://github.com/pyqtgraph/pyqtgraph/blob/pyqtgraph-0.13.7/LICENSE.txt). |
| NumPy | 2.2.6 | BSD-3-Clause plus bundled-library terms, including those in its wheel; [versioned license](https://github.com/numpy/numpy/blob/v2.2.6/LICENSE.txt). |
| pySerial | 3.5 | BSD-3-Clause and additional source notices; [versioned license](https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt). |
| PyInstaller | 6.13.0 | GPLv2 with a bundling exception, plus Apache-2.0 for specified files; [official terms](https://pyinstaller.org/en/v6.13.0/license.html). |

Apache-2.0 code can be included in a GPLv3 project; the Apache material keeps its own notices. This is the compatibility direction explained by the [Apache Software Foundation](https://www.apache.org/licenses/GPL-compatibility.html). ESP-IDF is not uniformly Apache-2.0: its component-specific notices take precedence, so the firmware's actual linked components must be checked.

PyInstaller's exception permits distributing generated bundles under the application's license, subject to dependency terms. It does not remove Qt, Python or NumPy obligations. Changes to PyInstaller itself have separate requirements under its license.

## Desktop distribution

The application uses Qt/PySide6 under the open-source LGPLv3 option. The application being GPLv3 does not erase the libraries' notices or source requirements. Preserve the notices for the exact bundled Qt and PySide components, not only a generic LGPL text. Qt lists its [third-party components](https://doc.qt.io/qt-6.8/licenses-used-in-qt.html), and Qt for Python has [additional notices](https://doc.qt.io/qtforpython-6.8/licenses.html).

Single-file packaging extracts DLLs at startup. That behavior alone does not demonstrate compliance with LGPLv3's replacement or recombination requirements. The release needs a practical way to build and run with modified compatible libraries. The generated application-source archive supplies application code and build scripts; matching library sources and their build information are a separate release requirement. This follows [LGPLv3 section 4](https://doc.qt.io/qt-6.8/lgpl.html).

See the [desktop distribution notes](desktop/THIRD_PARTY.md) for the source locations, rebuild procedure and remaining release work.

## Firmware distribution

The firmware links project code with ESP-IDF and its selected runtime components. A source checkout containing only `firmware/` is not the complete corresponding source of that linked image. A firmware release should identify the exact ESP-IDF revision, component revisions, build configuration and tools needed to reproduce it, and provide the required source access and license notices. Include the matching project source and any modified SDK components.

The prebuilt binaries in this tree are historical artifacts. Their build report says they were not tested on hardware. They have not been rebuilt as part of a documentation update, and their presence is not a completed license inventory for a new release.

## What has been resolved and what remains

The repository/desktop license mismatch has been corrected, the previous notice retained, and dependency obligations documented. The main dependencies do not require changing the project's GPLv3 license.

A public binary release still needs the exact bundled-file inventory, all applicable notices and matching corresponding source access. The current application-source ZIP does not include complete Qt/PySide/Shiboken or ESP-IDF sources. Upstream links help locate them; a distributor remains responsible for making the required source available under the license's conditions. Complete that release preparation for the actual binaries being published rather than treating a successful build as a compliance result.
