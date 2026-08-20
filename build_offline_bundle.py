"""Script to download Linux & universal wheel dependencies and build an offline, air-gapped deployment bundle."""
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
WHEELS_DIR = ROOT_DIR / "wheels"
DIST_DIR = ROOT_DIR / "dist"

CORE_PACKAGES = [
    "pynetbox>=7.0.0",
    "openpyxl>=3.1.0",
    "rich>=13.0.0",
    "requests>=2.28.0",
    "urllib3>=1.26.0",
    "setuptools",
    "wheel",
    "pip",
    "packaging",
    "certifi",
    "idna",
    "et_xmlfile",
    "markdown-it-py",
    "mdurl",
    "pygments",
    # Standalone virtual environment creation dependencies (for minimal OS without python3-venv)
    "virtualenv",
    "distlib",
    "filelock",
    "platformdirs",
    "python-discovery",
]

LINUX_PYTHON_VERSIONS = ["3.8", "3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]
LINUX_PLATFORMS = [
    "manylinux2014_x86_64",
    "manylinux_2_17_x86_64",
    "manylinux_2_28_x86_64",
    "manylinux2014_aarch64",
    "manylinux_2_17_aarch64",
]


def download_wheels():
    print("[1/4] Downloading wheel dependencies for offline Linux installation...")

    pip_exe = sys.executable

    # 1. Download universal / pure-python packages
    print("      -> Downloading universal & pure-python wheels...")
    cmd_universal = [
        pip_exe, "-m", "pip", "download",
        "-d", str(WHEELS_DIR),
        *CORE_PACKAGES
    ]
    subprocess.run(cmd_universal, check=False)

    # 2. Download Linux-specific binary wheels (e.g. charset_normalizer) for supported Python versions
    print("      -> Downloading Linux binary wheels for multiple Python versions (3.8-3.14, x86_64 & aarch64)...")
    for py_ver in LINUX_PYTHON_VERSIONS:
        ver_short = py_ver.replace(".", "")
        for plat in LINUX_PLATFORMS:
            cmd_linux = [
                pip_exe, "-m", "pip", "download",
                "-d", str(WHEELS_DIR),
                "--only-binary=:all:",
                "--platform", plat,
                "--python-version", py_ver,
                "--implementation", "cp",
                "--abi", f"cp{ver_short}",
                "charset-normalizer",
            ]
            subprocess.run(cmd_linux, capture_output=True, check=False)

    # 3. Build wheel for netbox-excel-importer itself
    print("[2/4] Building netbox-excel-importer wheel package...")
    cmd_build_pkg = [
        pip_exe, "-m", "pip", "wheel",
        "--no-deps",
        "-w", str(WHEELS_DIR),
        str(ROOT_DIR),
    ]
    subprocess.run(cmd_build_pkg, check=True)

    wheel_count = len(list(WHEELS_DIR.glob("*.whl")))
    print(f"      Total offline wheel packages assembled: {wheel_count}")


def build_offline_bundle():
    print("=== Building NetBox Importer Offline Deployment Bundle ===")

    # Ensure clean directories
    if WHEELS_DIR.exists():
        shutil.rmtree(WHEELS_DIR)
    WHEELS_DIR.mkdir(parents=True, exist_ok=True)

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Download dependencies & build package wheel
    download_wheels()

    # Files and directories to include in the bundle
    bundle_files = [
        "pyproject.toml",
        "README.md",
        "CHANGELOG.md",
        "install.sh",
        "install.ps1",
        "test_devices.xlsx",
        "src",
    ]

    # Create .tar.gz archive
    tar_path = DIST_DIR / "netbox_importer_offline_bundle.tar.gz"
    print(f"[3/4] Creating tarball archive: {tar_path}...")

    def set_tar_permissions(tarinfo):
        if tarinfo.name.endswith(".sh") or tarinfo.name.endswith(".ps1"):
            tarinfo.mode = 0o755
        return tarinfo

    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(WHEELS_DIR, arcname="wheels")
        for item in bundle_files:
            item_path = ROOT_DIR / item
            if item_path.exists():
                tar.add(item_path, arcname=item, filter=set_tar_permissions)

    # Create .zip archive
    zip_path = DIST_DIR / "netbox_importer_offline_bundle.zip"
    print(f"[4/4] Creating zip archive: {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(WHEELS_DIR):
            for file in files:
                fp = Path(root) / file
                rel = fp.relative_to(ROOT_DIR)
                zipf.write(fp, arcname=rel)

        for item in bundle_files:
            item_path = ROOT_DIR / item
            if item_path.is_dir():
                for root, _, files in os.walk(item_path):
                    for file in files:
                        fp = Path(root) / file
                        rel = fp.relative_to(ROOT_DIR)
                        zipf.write(fp, arcname=rel)
            elif item_path.is_file():
                zipf.write(item_path, arcname=item)

    print("\n=== Offline Bundle Created Successfully! ===")
    print(f"Tarball (.tar.gz): {tar_path} ({tar_path.stat().st_size / (1024*1024):.2f} MB)")
    print(f"Zipfile (.zip):   {zip_path} ({zip_path.stat().st_size / (1024*1024):.2f} MB)")


if __name__ == "__main__":
    build_offline_bundle()
