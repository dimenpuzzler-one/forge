"""Test bootstrap for Forge's intentionally separated Python packages."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for package_root in (
    ROOT / "apps" / "cli",
    ROOT / "packages" / "compose",
    ROOT / "packages" / "core",
    ROOT / "packages" / "project",
    ROOT / "packages" / "registry",
    ROOT / "packages" / "runtime",
    ROOT / "packages" / "sources",
    ROOT / "packages" / "search",
):
    sys.path.insert(0, str(package_root))
