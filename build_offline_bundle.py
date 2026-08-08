"""Script to download wheel dependencies and build an offline, air-gapped deployment bundle."""
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
WHEELS_DIR = ROOT_DIR / "wheels"
DIST_DIR = ROOT_DIR / "dist"


def build_offline_bundle():
    print("=== Building NetBox Importer Offline Deployment Bundle ===")
    
    # 1. Ensure wheels directory exists
    if WHEELS_DIR.exists():
        shutil.rmtree(WHEELS_DIR)
    WHEELS_DIR.mkdir(parents=True, exist_ok=True)

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Download wheel dependencies
    print("[1/3] Downloading wheel dependencies for offline installation...")
    cmd = [
        "python", "-m", "pip", "download",
        "-d", str(WHEELS_DIR),
        "pynetbox>=7.0.0",
        "openpyxl>=3.1.0",
        "rich>=13.0.0",
        "requests>=2.28.0",
        "urllib3>=1.26.0",
        "setuptools"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Error downloading wheels:")
        print(res.stderr)
        raise RuntimeError("Wheel download failed")
    print(f"      Downloaded {len(list(WHEELS_DIR.glob('*.whl')))} wheel packages to {WHEELS_DIR}")

    # 3. Define bundle contents
    bundle_files = [
        "pyproject.toml",
        "README.md",
        "install.sh",
        "install.ps1",
        "src",
    ]

    # 4. Create .tar.gz archive
    tar_path = DIST_DIR / "netbox_importer_offline_bundle.tar.gz"
    print(f"[2/3] Creating tarball archive: {tar_path}...")
    with tarfile.open(tar_path, "w:gz") as tar:
        # Add wheels
        tar.add(WHEELS_DIR, arcname="wheels")
        # Add source files
        for item in bundle_files:
            item_path = ROOT_DIR / item
            if item_path.exists():
                tar.add(item_path, arcname=item)

    # 5. Create .zip archive
    zip_path = DIST_DIR / "netbox_importer_offline_bundle.zip"
    print(f"[3/3] Creating zip archive: {zip_path}...")
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
