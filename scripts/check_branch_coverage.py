"""Check real branch arcs and discover browser gates as later suites arrive."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def branch_result(report: dict, source_root: Path) -> tuple[int, int]:
    """Return covered/total branches, rejecting reports missing source files."""
    expected = {path.resolve() for path in source_root.rglob("*.py")}
    reported = {}
    for name, details in report["files"].items():
        path = Path(name.replace("\\", "/"))
        path = path if path.is_absolute() else ROOT / path
        reported[path.resolve()] = details
    missing = expected - reported.keys()
    if missing:
        raise ValueError(f"Coverage report omits source files: {sorted(map(str, missing))}")
    covered = sum(reported[path]["summary"]["covered_branches"] for path in expected)
    total = sum(reported[path]["summary"]["num_branches"] for path in expected)
    return covered, total


def check_coverage(report_path: Path, domain: float, graph: float) -> int:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("meta", {}).get("branch_coverage"):
        raise ValueError("Coverage report must contain branch data")
    failed = False
    for name, threshold in (("domain", domain), ("graph", graph)):
        source_root = ROOT / "apps/api/src/bookgen" / name
        if not source_root.exists() or not any(source_root.rglob("*.py")):
            print(f"{name}: inactive (no source yet)")
            continue
        covered, total = branch_result(report, source_root)
        percentage = covered / total * 100 if total else 100.0
        print(f"{name}: {covered}/{total} branches ({percentage:.2f}%; required {threshold:g}%)")
        failed |= percentage < threshold
    return int(failed)


def browser_suites() -> tuple[bool, bool]:
    integration = ROOT / "apps/api/tests/integration"
    frontend = ROOT / "apps/web/tests/e2e"
    return (
        integration.exists() and any(integration.rglob("test_*.py")),
        frontend.exists() and any(
            path.is_file() and (".spec." in path.name or ".test." in path.name)
            for path in frontend.rglob("*")
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--domain", type=float, default=90)
    parser.add_argument("--graph", type=float, default=80)
    parser.add_argument("--prepare-browsers", action="store_true")
    parser.add_argument("--e2e", action="store_true")
    args = parser.parse_args()
    backend, frontend = browser_suites()
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    if args.prepare_browsers:
        if backend:
            subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], cwd=ROOT, check=True)
        if frontend:
            subprocess.run([npm, "--prefix", "apps/web", "exec", "--", "playwright", "install", "--with-deps", "chromium"], cwd=ROOT, check=True)
        if not (backend or frontend):
            print("Browser gates inactive (no integration/E2E tests yet)")
    elif args.e2e:
        if frontend:
            subprocess.run([npm, "--prefix", "apps/web", "run", "e2e"], cwd=ROOT, check=True)
        else:
            print("Frontend E2E inactive (no tests yet)")
    elif args.report:
        return check_coverage(args.report, args.domain, args.graph)
    else:
        parser.error("choose --report, --prepare-browsers or --e2e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
