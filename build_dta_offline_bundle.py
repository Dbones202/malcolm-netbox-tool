"""Package the DtA NetBox v2 offline air-gapped deployment bundle."""
import os
import tarfile
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
DEPLOY_DIR = ROOT_DIR / "deploy" / "dta-netbox-v2"
ZIP_OUT = ROOT_DIR / "dta-netbox-v2-offline.zip"
TAR_OUT = ROOT_DIR / "dta-netbox-v2-offline.tar.gz"


def package_dta_bundle():
    print(f"=== Packaging DtA NetBox v2 Offline Bundle from {DEPLOY_DIR} ===")

    if not DEPLOY_DIR.exists():
        raise FileNotFoundError(f"Deploy directory not found: {DEPLOY_DIR}")

    # 1. Build .zip archive
    print(f"[*] Creating ZIP archive: {ZIP_OUT}...")
    with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(DEPLOY_DIR):
            for file in sorted(files):
                if file == ".DS_Store":
                    continue
                fp = Path(root) / file
                rel = fp.relative_to(DEPLOY_DIR)
                arcname = Path("dta-netbox-v2") / rel
                
                # Set unix permissions if executable
                zinfo = zipfile.ZipInfo.from_file(fp, arcname=str(arcname))
                if file.endswith(".sh"):
                    zinfo.external_attr = 0o755 << 16  # rwxr-xr-x
                zipf.writestr(zinfo, fp.read_bytes())

    # 2. Build .tar.gz archive
    print(f"[*] Creating TAR.GZ archive: {TAR_OUT}...")
    def tar_filter(tarinfo):
        if tarinfo.name.endswith(".sh"):
            tarinfo.mode = 0o755
        return tarinfo

    with tarfile.open(TAR_OUT, "w:gz") as tar:
        tar.add(DEPLOY_DIR, arcname="dta-netbox-v2", filter=tar_filter)

    print("\n=== DtA v2 Offline Bundle Created Successfully! ===")
    print(f"ZIP:    {ZIP_OUT} ({ZIP_OUT.stat().st_size / (1024*1024):.2f} MB)")
    print(f"TAR.GZ: {TAR_OUT} ({TAR_OUT.stat().st_size / (1024*1024):.2f} MB)")


if __name__ == "__main__":
    package_dta_bundle()

