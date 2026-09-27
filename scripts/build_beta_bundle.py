"""Build an offline bundle from an explicit runtime and the tracked app source.

Run separately on each target OS. No workstation DB, .env, storage, or nested
checkout is selected. The supplied interpreter must be a relocatable runtime.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def selected(name: str) -> bool:
    path = Path(name)
    if path.name.startswith("test_") or path.name == "conftest.py":
        return False
    if name in {"LICENSE", "requirements.txt", "gen_bunnrei/bunrei.sqlite", "gen_bunnrei/facility.sqlite"}:
        return True
    if len(path.parts) == 1:
        return path.suffix == ".py"
    if path.parts[0] in {"routers", "child_records", "plan_docs", "scripts", "beta_setup", "windows_setup"}:
        if name == "windows_setup/components-lock.json":
            return True
        return path.suffix == ".py" or name.startswith("scripts/backup_contracts/") and path.suffix == ".json"
    return path.parts[0] in {"templates", "static", "assets"} and path.suffix.lower() not in {".db", ".sqlite", ".sqlite3", ".env"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-tag", help="Published tag, e.g. v2026.9.23.1; requires a clean source checkout")
    parser.add_argument("--server-components", type=Path)
    args = parser.parse_args()
    if args.release_tag:
        if not re.fullmatch(r"v[0-9][0-9A-Za-z.-]{0,79}", args.release_tag):
            raise ValueError("Invalid release tag")
        subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
        if any(name and (selected(name) or name.startswith("beta_setup/")) for name in untracked):
            raise ValueError("Commit the application and installer sources before building a release")
        if os.name != "nt":
            raise ValueError("This release builder currently publishes Windows x64 only")
    runtime = args.runtime.resolve()
    libraries = args.site_packages.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    executable = runtime / ("python.exe" if os.name == "nt" else "bin/python3")
    version = subprocess.check_output([str(executable), "-I", "-c", "import platform; print(platform.python_version())"], text=True).strip()
    if not version.startswith("3.12."):
        raise ValueError("Use a Python 3.12 runtime")
    if args.release_tag:
        machine = subprocess.check_output([str(executable), "-I", "-c", "import platform,struct; print(platform.machine().lower(),struct.calcsize('P')*8)"], text=True).strip()
        if machine not in {"amd64 64", "x86_64 64"}:
            raise ValueError("Use a Windows x64 Python runtime")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    sources = {f"app/{name}": ROOT / name for name in tracked if name and selected(name)}
    sources["app/_beta_runtime.py"] = ROOT / "beta_setup/runtime.py"
    if args.server_components:
        locked = json.loads((ROOT / "windows_setup/components-lock.json").read_text(encoding="utf-8"))
        for name in ("winsw.exe", "caddy.exe", "cloudflared.exe"):
            component = args.server_components.resolve() / name
            with component.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != locked[name]["sha256"]:
                    raise ValueError("Windows component checksum mismatch")
            sources["app/windows_setup/components/" + name] = component
    for path in runtime.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(runtime)
        if "site-packages" in relative.parts:
            continue
        sources[f"runtime/{relative.as_posix()}"] = path
    lib_prefix = "runtime/Lib/site-packages" if os.name == "nt" else "runtime/lib/python3.12/site-packages"
    for path in libraries.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            sources[f"{lib_prefix}/{path.relative_to(libraries).as_posix()}"] = path
    manifest = {"format": 1, "platform": sys.platform, "python": version,
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "packages": {d.metadata["Name"]: d.version for d in metadata.distributions(path=[str(libraries)])},
                "files": {}}
    if args.release_tag:
        manifest.update(release_tag=args.release_tag, architecture="x64",
                        minimum_installer_protocol=2 if args.server_components else 1, runtime_protocol=1)
    if args.server_components:
        manifest["server_protocol"] = 1
    archive = output / "payload.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for name, path in sorted(sources.items()):
            data = path.read_bytes()
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            package.writestr(info, data)
            manifest["files"][name] = hashlib.sha256(data).hexdigest()
    with archive.open("rb") as stream:
        manifest["archive_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest["archive_bytes"] = archive.stat().st_size
    shutil.copyfile(args.launcher, output / args.launcher.name)
    (output / args.launcher.name).chmod(0o700)
    (output / "bundle.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.release_tag:
        shutil.copyfile(archive, output / "OpenHoikuICT-windows-x64.zip")
        shutil.copyfile(output / "bundle.json", output / "OpenHoikuICT-windows-x64.json")
    (output / "START-HERE.txt").write_text(
        "OpenHoikuICT - local beta\n\n"
        "1. Extract the complete folder to a local disk.\n"
        "2. Open OpenHoikuICT.exe to download the latest verified release.\n"
        "3. Follow the three setup screens in the browser.\n\n"
        "Use fictional data. Facility HTTPS/SMTP setup is not included.\n"
        "After setup, the same launcher is in the selected installation folder.\n"
        "Keep the app and runtime folders with the launcher.\n"
        "Use the Exit button to stop the app and close its local controller.\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "python": version, "files": len(sources),
                      "archive_bytes": archive.stat().st_size, "sha256": manifest["archive_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
