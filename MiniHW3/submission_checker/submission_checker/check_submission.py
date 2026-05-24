"""Validate a student zip against the HW contract using reference.zip."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REFERENCE_ZIP = ROOT / "reference.zip"
REQUIRED = (
    "app.py",
    "mock_database.py",
    "test_app.py",
    "test_app_new.py",
)
TARGET = {
    "app.py": "app.py",
    "mock_database.py": "database/mock_database.py",
    "test_app.py": "tests/test_app.py",
    "test_app_new.py": "tests/test_app_new.py",
}
REQ_TESTS = ("test_initial_empty", "test_add_product", "test_remove_product")
TEST_DEF = re.compile(r"^\s+def (test\w*)\s*\(", re.MULTILINE)
MAX_CHANGED_LINES = 5


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"OK: {msg}")


def safe_extract(zf: zipfile.ZipFile, dst: Path) -> None:
    dst = dst.resolve()
    for info in zf.infolist():
        name = info.filename.replace("\\", "/").strip("/")
        if not name:
            continue
        path = Path(name)
        if ".." in path.parts or path.is_absolute():
            raise ValueError(f"unsafe zip path: {name}")
        out = (dst / path).resolve()
        out.relative_to(dst)
        if info.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zf.read(info.filename))


def changed_lines(old: str, new: str) -> int:
    """Fair metric: replacements count once (not delete+add)."""
    sm = difflib.SequenceMatcher(a=old.splitlines(), b=new.splitlines())
    total = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            total += max(i2 - i1, j2 - j1)
    return total


def ensure_required_submission(root: Path) -> dict[str, Path]:
    files = [p for p in root.rglob("*") if p.is_file()]
    rels = sorted(str(p.relative_to(root)).replace("\\", "/") for p in files)
    if rels == sorted(REQUIRED):
        return {TARGET[rel]: root / rel for rel in rels}
    fail(
        "Submission zip must contain only these 4 files: "
        "app.py, mock_database.py, test_app.py, test_app_new.py (at zip root)."
    )


def zip_matches_submission_contract(zpath: Path) -> bool:
    try:
        with zipfile.ZipFile(zpath) as zf:
            names: list[str] = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/").strip("/")
                if name:
                    names.append(name)
    except zipfile.BadZipFile:
        return False
    return sorted(names) == sorted(REQUIRED)


def resolve_submission_zip(arg_zip: Path | None) -> Path:
    if arg_zip is not None:
        if not arg_zip.is_file():
            fail(f"zip not found: {arg_zip}")
        return arg_zip

    candidates = []
    for zpath in ROOT.glob("*.zip"):
        if zpath.resolve() == REFERENCE_ZIP.resolve():
            continue
        if zip_matches_submission_contract(zpath):
            candidates.append(zpath)

    if len(candidates) == 1:
        ok(f"auto-detected submission zip: {candidates[0].name}")
        return candidates[0]
    if len(candidates) == 0:
        fail(
            "No valid submission zip found next to check_submission.py. "
            "Place one zip with exactly: app.py, mock_database.py, test_app.py, test_app_new.py."
        )
    chosen = max(candidates, key=lambda p: p.stat().st_mtime)
    ok(f"auto-detected submission zip: {chosen.name} (newest valid zip)")
    return chosen


def run_tests(workspace: Path) -> tuple[int, str, float]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    t0 = time.perf_counter()
    p = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_app*.py"],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed = time.perf_counter() - t0
    return p.returncode, (p.stdout or "") + (p.stderr or ""), elapsed


def extract_unittest_runtime(output: str) -> float | None:
    match = re.search(r"Ran\s+\d+\s+tests?\s+in\s+([0-9]*\.?[0-9]+)s", output)
    if not match:
        return None
    return float(match.group(1))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Validate submission zip (app.py + mock_database.py + "
            "test_app.py + test_app_new.py). "
            "Line metric counts changed logical lines; <=5 passes."
        )
    )
    ap.add_argument("submission_zip", nargs="?", type=Path)
    args = ap.parse_args()

    submission_zip = resolve_submission_zip(args.submission_zip)
    if not REFERENCE_ZIP.is_file():
        fail(f"reference.zip not found next to checker: {REFERENCE_ZIP}")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        reference_root = td_path / "reference"
        submitted_root = td_path / "submitted"
        workspace = td_path / "workspace"

        with zipfile.ZipFile(REFERENCE_ZIP) as zf:
            safe_extract(zf, reference_root)
        with zipfile.ZipFile(submission_zip) as zf:
            safe_extract(zf, submitted_root)

        submitted = ensure_required_submission(submitted_root)
        shutil.copytree(reference_root, workspace)

        ref_app = (workspace / "app.py").read_text(encoding="utf-8")
        ref_test = (workspace / "tests/test_app.py").read_text(encoding="utf-8")
        ref_mock = (workspace / "database/mock_database.py").read_text(encoding="utf-8")
        ref_new = (workspace / "tests/test_app_new.py").read_text(encoding="utf-8")

        for rel, src in submitted.items():
            dst = workspace / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        app_src = (workspace / "app.py").read_text(encoding="utf-8")
        test_src = (workspace / "tests/test_app.py").read_text(encoding="utf-8")
        mock_src = (workspace / "database/mock_database.py").read_text(encoding="utf-8")
        new_src = (workspace / "tests/test_app_new.py").read_text(encoding="utf-8")

        app_delta = changed_lines(ref_app, app_src)
        test_delta = changed_lines(ref_test, test_src)
        if app_delta > MAX_CHANGED_LINES:
            fail(f"app.py changed lines {app_delta} > {MAX_CHANGED_LINES}")
        if test_delta > MAX_CHANGED_LINES:
            fail(f"tests/test_app.py changed lines {test_delta} > {MAX_CHANGED_LINES}")
        ok(f"line budgets pass (app.py={app_delta}, tests/test_app.py={test_delta})")

        for name in REQ_TESTS:
            if not re.search(rf"^\s+def {re.escape(name)}\b", test_src, re.MULTILINE):
                fail(f"tests/test_app.py missing required test: {name}")
        if len(TEST_DEF.findall(test_src)) != 3:
            fail("tests/test_app.py must contain exactly 3 test_* methods")

        extra_count = len(TEST_DEF.findall(new_src))
        if extra_count < 2:
            fail("tests/test_app_new.py must contain at least 2 test_* methods")
        if new_src == ref_new:
            fail("tests/test_app_new.py was not changed from template")
        ok("tests/test_app_new.py changed (content will be graded manually)")

        if mock_src == ref_mock:
            fail("database/mock_database.py was not changed from template")
        ok("mock template complete")

        code, out, elapsed = run_tests(workspace)
        test_runtime = extract_unittest_runtime(out)
        effective_runtime = test_runtime if test_runtime is not None else elapsed
        ok(f"tests runtime: {effective_runtime:.2f}s")
        if effective_runtime > 2.0:
            fail("tests exceeded 2 seconds")
        print(out.rstrip())
        if code != 0:
            fail("unittest failed")

        ran = re.findall(r"Ran\s+(\d+)\s+test", out)
        if not ran or int(ran[-1]) < 5:
            fail("expected at least 5 tests total (3 required + 2 extra)")
        ok(f"ran {ran[-1]} tests")

    ok("all checks passed")


if __name__ == "__main__":
    main()
