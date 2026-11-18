# Desktop licenses and distribution

The IoT Current Scope application is distributed under **GNU GPL version 3**, in [LICENSE](LICENSE), matching the repository. Copyright and previous attribution are retained in the bundled notices. The original MIT notice from the initial desktop draft is kept in `licenses/PROJECT-ORIGINAL-MIT.txt`; it does not change the license of the current project as a whole.

This file describes the open-source Qt distribution route used by the project. A successful PyInstaller build is not by itself a completed license review of its output.

## Bundled components

| Component | Pinned version | License and corresponding source location |
|---|---|---|
| Python | 3.12 x64 | PSF and incorporated-code terms; [release sources](https://www.python.org/downloads/source/) and [license](https://docs.python.org/3.12/license.html). |
| Qt | 6.8.3 | LGPLv3 for the selected libraries, plus third-party terms; [versioned module sources](https://download.qt.io/archive/qt/6.8/6.8.3/submodules/). |
| PySide6 / Shiboken | 6.8.3 | LGPLv3/GPLv3 or commercial; [matching source release](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/). |
| pyqtgraph | 0.13.7 | MIT; [versioned source](https://github.com/pyqtgraph/pyqtgraph/tree/pyqtgraph-0.13.7). |
| NumPy | 2.2.6 | BSD and bundled-library terms; [versioned source](https://github.com/numpy/numpy/tree/v2.2.6). Preserve the wheel's full notices, including its numerical libraries. |
| pySerial | 3.5 | BSD-3-Clause and incorporated-code notices; [versioned source](https://github.com/pyserial/pyserial/tree/v3.5). |
| PyInstaller | 6.13.0 | GPL with a generated-bundle exception; [official license](https://pyinstaller.org/en/v6.13.0/license.html). Build tooling retains its own terms. |

The Windows executable inspected on 18 November 2026 contains Qt **Core, Gui, Network, OpenGL, OpenGLWidgets, Svg, Test and Widgets** DLLs, plus the `qtbase_pt_BR.qm` translation catalog. No Virtual Keyboard component was found. The complete collected filenames and versions are recorded in `../validation/windows_bundle.json`. Repeat this inspection for each release: the installed `PySide6` wheel contains more modules than the application uses, so installation alone is not a reliable inventory of shipped components.

The custom packaging hook excludes Qt Virtual Keyboard and unused PDF/image plugins. Those exclusions keep the package smaller and avoid collecting unrelated components. They do not replace reviewing the remaining binary inventory. Qt includes its own [third-party code and notices](https://doc.qt.io/qt-6.8/licenses-used-in-qt.html), and [Qt for Python also has third-party notices](https://doc.qt.io/qtforpython-6.8/licenses.html).

## Qt and single-file packaging

Qt/PySide6 is available under LGPLv3/GPLv3 or commercial terms. This project follows the LGPLv3 option for the selected libraries. The application prominently identifies that use in its license information and includes GPLv3/LGPLv3 texts.

PyInstaller's single-file mode extracts bundled DLLs to a temporary directory. This does not, on its own, prove that a recipient can replace them persistently or recombine the application with a modified library. The intended release route is to provide the application source, matching library source and enough build information to produce and run a modified package. See [LGPLv3 section 4](https://doc.qt.io/qt-6.8/lgpl.html).

Recipients must retain the ability to modify the library portions and reverse engineer the combined work to debug those changes. Do not add an installer agreement or distribution restriction that removes those rights. Qt's own [LGPL obligations guide](https://www.qt.io/development/open-source-lgpl-obligations) describes source availability, relinking, installation information and notices.

## Rebuilding with a compatible modified library

`build_windows.bat` creates `IoTCurrentScope-source.zip` with the application, SVG assets, test files, build recipe and collected notices. The archive contains application sources; it does **not** contain the complete sources of Qt, PySide6, Shiboken or all their incorporated libraries.

To rebuild the application:

1. Extract the source archive to a writable directory on Windows and install Python 3.12 x64.
2. Run `build_windows.bat` once to prepare `.venv` and check the standard build.
3. Build the desired compatible Qt/PySide6/Shiboken versions from their matching source, following the [Qt for Python build instructions](https://doc.qt.io/qtforpython-6.8/building_from_source/index.html). Preserve local changes and the commands/configuration used to build them.
4. Install the modified packages into `.venv`, retaining the pinned version identifiers and compatible interfaces. Do not use a forced dependency reinstall afterward, because it would replace those packages.
5. Run the build recipe again. Its dependency check should accept matching installed versions. Verify that the resulting package actually uses the modified libraries, then exercise the packaged self-test and normal operation.

This procedure describes the application's rebuild path. A distributor of a particular binary must additionally supply the exact library source, patches and build/install information necessary for that release, and verify this path using those materials. A generic upstream homepage is not that evidence.

## Preparing a release

Publish the EXE together with the matching application-source archive, the complete required library sources and the applicable notices. For download distribution, keep equivalent source access available and give clear directions next to the binary. Identify exact Python patch level, wheels, Qt libraries/plugins and any changes. Preserve relevant third-party license texts from those exact artifacts.

The source and notice requirements continue to apply when libraries have not been modified. The project includes license texts and collects dependency notices during packaging, but it does not automatically download and publish a complete corresponding-source bundle. That remains release work for the actual package being distributed.

PyInstaller's exception allows the generated bundle to use the application's GPLv3 license, subject to dependencies; it does not impose PyInstaller's GPLv2 on application code. If distributing a modified PyInstaller itself, follow its own terms separately.

The repository-wide review is in [../THIRD_PARTY.md](../THIRD_PARTY.md). No binary in this source tree is declared distribution-complete solely by this document.

The current Windows build passed its packaged functional self-test, as recorded in [VALIDATION.md](../VALIDATION.md). That result verifies the application path and recorded bundle inventory; matching library-source access and complete third-party notices remain release requirements.
