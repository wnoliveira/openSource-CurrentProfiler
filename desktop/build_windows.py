"""Build and test the Windows one-file bundle before publishing it to dist.

The previous executable remains available if compilation or the packaged
self-test fails. The accompanying source archive includes the rebuild scripts
and license notices.
"""

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile


ROOT = Path(__file__).resolve().parent


def check_output_writable(path):
    """Detect a running executable or unwritable output before starting a build."""
    if not path.exists():
        return
    try:
        with path.open("r+b"):
            pass
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot replace {path}. Close IoTCurrentScope.exe "
            "and check write permission for the dist folder."
        ) from exc


def run(command, log, *, cwd=ROOT, env=None, timeout=None):
    """Preserve subprocess diagnostics, including failures without a console."""
    command_text = subprocess.list2cmdline([str(argument) for argument in command])
    log.write("\n> " + command_text + "\n")
    log.flush()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            f"Command exited with code {result.returncode}. Check the build log."
        )


def source_archive(destination, licenses):
    """Include the files needed to rebuild the application with other Qt DLLs."""
    top_level_files = (
        "main.py",
        "build_windows.py",
        "build_windows.bat",
        "run_windows.bat",
        "IoTCurrentScope.spec",
        "requirements.txt",
        "requirements-build.txt",
        "README.md",
        "THIRD_PARTY.md",
        "LICENSE",
    )
    files = [ROOT / name for name in top_level_files]
    files += sorted((ROOT / "current_scope").rglob("*.py"))
    files += sorted((ROOT / "current_scope" / "assets").rglob("*.svg"))
    files += sorted((ROOT / "tests").glob("*.py"))
    files += sorted((ROOT / "hooks").glob("*.py"))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
        for path in sorted(licenses.rglob("*")):
            if path.is_file():
                archive.write(path, Path("licenses") / path.relative_to(licenses))


def publish(source, destination):
    """Replace an output with rollback if moving the new artifact fails."""
    # Some Windows file filters deny replacement but allow a rename. Retain
    # the previous artifact until the tested replacement has its final name.
    backup = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.previous")
    if destination.exists():
        destination.rename(backup)
    try:
        source.replace(destination)
    except OSError:
        if backup.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        backup.unlink()


def portable_test_environment(build_environment):
    """Remove developer paths that could hide missing DLLs in the bundle."""
    environment = build_environment.copy()
    developer_settings = (
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "QT_PLUGIN_PATH",
        "QML2_IMPORT_PATH",
        "QML_IMPORT_PATH",
    )
    for key in developer_settings:
        environment.pop(key, None)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join([str(windows / "System32"), str(windows)])
    return environment


def build(log):
    """Prepare dependencies, build in staging, test, then publish the artifacts."""
    is_windows = sys.platform == "win32"
    is_python312 = sys.version_info[:2] == (3, 12)
    is_64_bit = struct.calcsize("P") == 8
    if not (is_windows and is_python312 and is_64_bit):
        raise RuntimeError("Build on Windows with 64-bit Python 3.12.")

    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    executable = output / "IoTCurrentScope.exe"
    sources = output / "IoTCurrentScope-source.zip"
    check_output_writable(executable)
    check_output_writable(sources)

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        print("Creating the Python environment...", flush=True)
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")], log)

    environment_check = (
        "import struct, sys; "
        "valid = sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8; "
        "sys.exit(not valid)"
    )
    try:
        run([str(python), "-c", environment_check], log)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            "The .venv folder is invalid or uses a different Python version. "
            "Rename it and build again to create a Python 3.12 x64 environment."
        ) from exc

    print("Checking build dependencies...", flush=True)
    run(
        [
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(ROOT / "requirements-build.txt"),
        ],
        log,
    )
    run([str(python), "-m", "pip", "check"], log)

    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(ROOT / "build" / "cache")
    # Staging keeps a failed build or test from replacing a usable executable.
    with tempfile.TemporaryDirectory(prefix="package-", dir=ROOT / "build") as folder:
        staging = Path(folder)
        print("Building the one-file executable. Please wait...", flush=True)
        run(
            [
                str(python), "-m", "PyInstaller", "--clean", "--noconfirm",
                "--distpath", str(staging),
                "--workpath", str(ROOT / "build" / "pyinstaller"),
                str(ROOT / "IoTCurrentScope.spec"),
            ],
            log,
            env=environment,
        )

        print("Testing the EXE: interface, DEMO, SVG and CSV/PNG exports...", flush=True)
        report = staging / "self-test.json"
        working_folder = staging / "portable test"
        working_folder.mkdir()
        try:
            run(
                [str(staging / "IoTCurrentScope.exe"), "--self-test", str(report)],
                log,
                cwd=working_folder,
                env=portable_test_environment(environment),
                timeout=60,
            )
        finally:
            if report.is_file():
                log.write(report.read_text(encoding="utf-8") + "\n")
                log.flush()

        if not report.is_file():
            raise RuntimeError("The executable did not write its self-test report.")
        test_result = json.loads(report.read_text(encoding="utf-8"))
        if test_result.get("status") != "ok":
            raise RuntimeError("The executable failed its self-test. Check the log.")

        source_archive(staging / sources.name, ROOT / "build" / "licenses")
        # The previous application may have been opened while the build ran.
        check_output_writable(executable)
        check_output_writable(sources)
        publish(staging / sources.name, sources)
        publish(staging / executable.name, executable)
        (output / "self-test.json").write_text(
            report.read_text(encoding="utf-8"), encoding="utf-8"
        )
    print(f"Executable built and tested: {executable}")
    print(f"Source code and license notices: {sources}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-pause", action="store_true", help="used by the .bat launcher")
    parser.parse_args()
    (ROOT / "build").mkdir(exist_ok=True)
    log_path = ROOT / "build" / "build_windows.log"
    with log_path.open("w", encoding="utf-8") as log:
        try:
            build(log)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            message = f"Executable build failed: {exc}"
            log.write(message + "\n")
            print(message, file=sys.stderr)
            print(f"Full diagnostics: {log_path}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
