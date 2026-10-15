"""Stage a smaller installer payload without changing the working application."""

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BROWSER_LANGUAGES = {"en-us", "en-gb", "zh-cn", "zh-tw"}


def include_file(relative: Path) -> bool:
    name = relative.name.casefold()
    parts = [part.casefold() for part in relative.parts]
    if name.endswith((".debug.pak", ".pdb")):
        return False
    if "qtwebengine_locales" in parts and relative.suffix.casefold() == ".pak":
        return relative.stem.casefold() in BROWSER_LANGUAGES
    if "translations" in parts and relative.suffix.casefold() == ".qm":
        return name.endswith(("_en.qm", "_en_us.qm", "_en_gb.qm", "_zh_cn.qm", "_zh_tw.qm"))
    return True


def main():
    source = ROOT / "dist" / "静读"
    destination = ROOT / ".build" / "installer-payload"
    if not (source / "静读.exe").is_file():
        raise SystemExit("Build dist/静读 first.")
    # Only this dedicated staging directory may be replaced on subsequent builds.
    if destination.resolve().parent != (ROOT / ".build").resolve() or destination.name != "installer-payload":
        raise SystemExit("Unexpected installer staging path.")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    original_size = payload_size = 0
    removed = []
    for file in source.rglob("*"):
        if not file.is_file():
            continue
        relative = file.relative_to(source)
        size = file.stat().st_size
        original_size += size
        if not include_file(relative):
            removed.append({"path": relative.as_posix(), "bytes": size})
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        payload_size += size
    report = {"original_bytes": original_size, "payload_bytes": payload_size,
              "removed_bytes": original_size - payload_size, "removed_files": removed}
    (ROOT / ".build" / "installer-size.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Original: {original_size / 1048576:.1f} MiB; payload: {payload_size / 1048576:.1f} MiB")


if __name__ == "__main__":
    main()
