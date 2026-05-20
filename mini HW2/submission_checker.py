#!/usr/bin/env python3
import os
import sys
import zipfile
import shutil
import subprocess
from pathlib import Path

import numpy as np
from sklearn.datasets import fetch_openml
from PIL import Image

def error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)

def on_rm_error(func, path, exc_info):
    """
    Error handler for shutil.rmtree.
    If the removal failed because the file is read-only, make it writable and retry.
    """
    import stat
    # Remove read-only flag
    os.chmod(path, stat.S_IWRITE)
    # Try again
    func(path)

def safe_rmtree(path):
    """Remove a directory tree even if Windows has set read-only flags."""
    if path.exists():
        shutil.rmtree(path, onerror=on_rm_error)

def main():
    # --- 1) find the ZIP file ---
    zips = list(Path('.').glob('*.zip'))
    if len(zips) != 1:
        error("Please place exactly one .zip in this folder (the student submission).")
    zip_path = zips[0]
    print(f"Found submission: {zip_path.name}")

    # --- 2) unzip into submission/ ---
    subdir = Path('submission')
    safe_rmtree(subdir)
    subdir.mkdir()
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(subdir)
    print("Unzipped into ./submission/")

    # --- 3) check required files ---
    required = ['requirements.txt', 'Dockerfile', 'docker-compose.yml']
    missing = [f for f in required if not (subdir / f).is_file()]
    if missing:
        error(f"Missing required files: {', '.join(missing)}")
    print("All required files present.")

    # --- 4) prepare Data/ with 40 random MNIST images ---
    data_dir = subdir / 'Data'
    safe_rmtree(data_dir)
    data_dir.mkdir()
    print("Downloading MNIST (may take a moment)...", end='', flush=True)
    mnist = fetch_openml('mnist_784', version=1, as_frame=False)
    X = mnist['data']
    print(" done.")
    idx = np.random.choice(len(X), 40, replace=False)
    for i, j in enumerate(idx):
        arr = X[j].reshape(28, 28).astype(np.uint8)
        img = Image.fromarray(arr, mode='L')
        img.save(data_dir / f"img{i}.png")
    print("Saved 40 MNIST samples to submission/Data/")

    # --- 5) ensure Predictions/ exists for volume mount ---
    pred_dir = subdir / 'Predictions'
    safe_rmtree(pred_dir)
    pred_dir.mkdir()
    print("Created empty submission/Predictions/")

    # --- 6) build & run student Docker image ---
    print("Building and running Docker…")
    res = subprocess.run(
        ["docker", "compose", "up", "--build"],
        cwd=subdir
    )
    if res.returncode != 0:
        error("`docker compose up` failed.")
    # tear down
    subprocess.run(["docker", "compose", "down"], cwd=subdir, stdout=subprocess.DEVNULL)

    # --- 7) verify number of outputs ---
    out_files = list(pred_dir.glob('*'))
    count = len([f for f in out_files if f.suffix.lower() in ('.png','.jpg','.jpeg')])
    if count != 40:
        error(f"Expected 40 predictions, but found {count}.")
    print("Success! Found 40 prediction files in submission/Predictions/")

if __name__ == '__main__':
    main()
