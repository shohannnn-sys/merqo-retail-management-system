"""Post-install verification for the Windows build (run inside CI).

Checks, in order:
  1. the installed executable and its bundled resources exist;
  2. the app starts, initialises its database under %LOCALAPPDATA% and renders
     every screen offscreen, writing screenshots;
  3. an offline license issued by an ephemeral CI key activates successfully;
  4. no business data is written next to the executable.

    python tools/verify_install.py --exe "C:\\...\\Retvia.exe" --screenshots build/shots

Exit code 0 means every check passed. Anything else fails the build.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def check(label: str, condition: bool, detail: str = "") -> bool:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, required=True)
    parser.add_argument("--license-file", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    results: list[bool] = []
    exe = args.exe.resolve()
    results.append(check("executable exists", exe.is_file(), str(exe)))
    if not exe.is_file():
        return 1

    internal = exe.parent / "_internal"
    root = internal if internal.is_dir() else exe.parent
    results.append(
        check(
            "bundled Bangla font present",
            (root / "retvia" / "assets" / "fonts" / "NotoSansBengali.ttf").is_file(),
        )
    )
    results.append(
        check(
            "bundled migrations present",
            (root / "retvia" / "data" / "migrations" / "0001_initial.sql").is_file(),
        )
    )
    results.append(
        check(
            "public verification key bundled",
            (root / "retvia" / "assets" / "license_public_key.json").is_file(),
        )
    )

    data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix="retvia-verify-"))
    environment = dict(os.environ)
    environment["RETVIA_DATA_DIR"] = str(data_dir)
    environment["QT_QPA_PLATFORM"] = "windows"
    args.screenshots.mkdir(parents=True, exist_ok=True)

    command = [str(exe), "--smoke-test", "--screenshot-dir", str(args.screenshots)]
    print(f"Launching: {' '.join(command)}")
    try:
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        check("app smoke run completes", False, f"timed out after {args.timeout}s")
        return 1

    results.append(
        check("app smoke run exits cleanly", completed.returncode == 0, f"exit={completed.returncode}")
    )
    if completed.stdout.strip():
        print("--- stdout ---")
        print(completed.stdout[-4000:])
    if completed.stderr.strip():
        print("--- stderr ---")
        print(completed.stderr[-4000:])

    result_file = args.screenshots / "smoke-result.txt"
    if result_file.is_file():
        summary = result_file.read_text(encoding="utf-8")
        print("--- page summary ---")
        print(summary)
        results.append(check("every screen rendered", "failures=0" in summary))
    else:
        results.append(check("page summary written", False))

    shots = sorted(args.screenshots.glob("*.png"))
    results.append(check("screenshots captured", len(shots) >= 15, f"{len(shots)} images"))

    database = data_dir / "data" / "retvia.db"
    results.append(check("database created in the user data directory", database.is_file(), str(database)))
    results.append(check("backup folder created", (data_dir / "backups").is_dir()))
    results.append(check("log folder created", (data_dir / "logs").is_dir()))
    results.append(
        check(
            "no database beside the executable",
            not (exe.parent / "retvia.db").exists() and not (exe.parent / "data" / "retvia.db").exists(),
        )
    )

    if database.is_file():
        import sqlite3

        with sqlite3.connect(database) as connection:
            version = connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[
                0
            ]
            tables = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        results.append(check("schema migrated", version >= 3, f"version={version}"))
        results.append(check("all tables created", tables >= 39, f"{tables} tables"))
        results.append(check("database integrity", integrity == "ok", integrity))

    if args.license_file and args.license_file.is_file():
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        os.environ["RETVIA_DATA_DIR"] = str(data_dir)
        from retvia.services.container import ServiceContainer

        container = ServiceContainer(data_dir)
        try:
            key = args.license_file.read_text(encoding="utf-8").strip()
            activation = container.activation.activate(key)
            results.append(check("offline activation succeeds", activation["activated"] is True))
            verified = container.activation.verify()
            results.append(check("license re-verifies on relaunch", verified["activated"] is True))
            recovery = container.activation.recovery_request()
            results.append(
                check(
                    "hardware fingerprint generated",
                    bool(recovery["current_fingerprint"].get("components")),
                    json.dumps(sorted(recovery["current_fingerprint"]["components"])),
                )
            )
        except Exception as exc:  # noqa: BLE001 - report the failure, do not crash the runner
            results.append(check("offline activation succeeds", False, str(exc)))
        finally:
            container.close()

    passed = sum(results)
    total = len(results)
    print()
    print(f"RESULT: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
