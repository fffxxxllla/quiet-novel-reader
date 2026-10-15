"""Install into an isolated project directory, check the app, then uninstall."""

import hashlib
import json
import os
import subprocess
import time
import winreg
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6C0FFB91-52BE-42DE-B93F-631B5E0DC216}_is1"


def registered() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY):
            return True
    except FileNotFoundError:
        return False


def digest(file: Path) -> str:
    checksum = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def shortcut_backups() -> dict[Path, bytes | None]:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
        desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        programs = Path(winreg.QueryValueEx(key, "Programs")[0])
    paths = (desktop / "静读.lnk", programs / "静读" / "静读.lnk", programs / "静读" / "书架.lnk")
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def main():
    installer = ROOT / "releases" / "静读-1.1.0-安装包.exe"
    target = ROOT / ".build" / "installer-smoke"
    profile = ROOT / ".build" / "installer-smoke-profile"
    if target.exists() or registered():
        raise SystemExit("An installation already exists. Refusing to overwrite it for this check.")
    if target.resolve().parent != (ROOT / ".build").resolve():
        raise SystemExit("Unexpected test installation directory.")
    profile.mkdir(parents=True, exist_ok=True)
    sentinel = profile / "reading-record.json"
    sentinel.write_text('{"book_title": "保留阅读记录"}', encoding="utf-8")
    environment = dict(os.environ, QNR_CONFIG_DIR=str(profile))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    shortcuts = shortcut_backups()
    result = {"ok": False, "checks": [], "installer_bytes": installer.stat().st_size}
    try:
        subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                        "/NOICONS", "/TASKS=", "/LANG=chinesesimp", "/DIR=" + str(target),
                        "/LOG=" + str(ROOT / ".build" / "installer-smoke-install.log")],
                       check=True, timeout=180, startupinfo=startup)
        assert (target / "静读.exe").is_file()
        assert registered()
        result["checks"].append("per-user installation and Windows uninstall registration")
        payload = ROOT / ".build" / "installer-payload"
        count = 0
        for source in payload.rglob("*"):
            if source.is_file():
                installed = target / source.relative_to(payload)
                assert installed.is_file(), str(installed)
                assert digest(installed) == digest(source), str(installed)
                count += 1
        result["checked_files"] = count
        result["checks"].append("all installed files match the validated payload")
        report = ROOT / ".build" / "installed-app-check.json"
        subprocess.run([str(target / "静读.exe"), "--self-check", str(report)],
                       check=True, timeout=60, env=environment, startupinfo=startup)
        assert json.loads(report.read_text(encoding="utf-8"))["ok"]
        result["checks"].append("installed bookshelf, reading appearance and WebEngine self-check")
    finally:
        try:
            uninstaller = target / "unins000.exe"
            if uninstaller.is_file():
                subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                "/LOG=" + str(ROOT / ".build" / "installer-smoke-uninstall.log")],
                               check=True, timeout=90, startupinfo=startup)
                deadline = time.monotonic() + 15
                while (target / "静读.exe").exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
        finally:
            # Inno can create group icons even with /NOICONS when the group
            # page is disabled. Restore any existing reader shortcuts exactly.
            for path, content in shortcuts.items():
                if content is None:
                    path.unlink(missing_ok=True)
                elif not path.exists() or path.read_bytes() != content:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
    assert not (target / "静读.exe").exists()
    assert not registered()
    assert sentinel.read_text(encoding="utf-8") == '{"book_title": "保留阅读记录"}'
    result["checks"].append("uninstall removes app registration and preserves reading data")
    result["ok"] = True
    (ROOT / ".build" / "installer-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
