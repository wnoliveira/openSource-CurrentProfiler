"""Refresh source and validation hashes after editing this distribution.

Run from any directory with Python. Build folders, local environments and the
manifest itself are excluded; historical prebuilt images keep their own hashes.
"""

import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {".venv", ".python312", "build", "dist", "__pycache__"}


def source_files():
    for name in ("README.md", "README.pdf", "LICENSE", "THIRD_PARTY.md", "VALIDATION.md", ".gitignore"):
        yield ROOT / name
    for name in ("desktop", "firmware", "docs", "tests", "tools", "validation"):
        for folder, directories, filenames in os.walk(ROOT / name):
            directories[:] = [directory for directory in directories
                              if directory not in EXCLUDED_DIRECTORIES]
            for filename in filenames:
                if filename.endswith(".pyc") or filename in ("sdkconfig", "sdkconfig.old"):
                    continue
                yield Path(folder) / filename


def main():
    hashes = {}
    for path in sorted(source_files()):
        if path.is_file():
            relative = path.relative_to(ROOT).as_posix()
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = ROOT / "MANIFEST_SHA256.json"
    manifest.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {manifest.name}: {len(hashes)} files")


if __name__ == "__main__":
    main()
