"""Extraction of portrait depth maps embedded in HEIC files."""

from pathlib import Path
import shutil
import subprocess
import tempfile


def _extract_aux(source: Path, destination: Path, marker: str) -> Path | None:
    if source.suffix.casefold() not in {".heic", ".heif"} or not shutil.which("heif-convert"):
        return None
    if destination.is_file():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-waste-depth-") as directory:
        output = Path(directory) / "image.jpg"
        try:
            subprocess.run(["heif-convert", "--with-aux", "--quiet", str(source), str(output)], check=True, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        matches = sorted(output.parent.glob(f"image-{marker}*.jpg"))
        if not matches:
            return None
        auxiliary = matches[0]
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            shutil.copyfile(auxiliary, temporary)
            temporary.replace(destination)
        except OSError:
            temporary.unlink(missing_ok=True)
            return None
    return destination


def extract(source: Path, destination: Path) -> Path | None:
    return _extract_aux(source, destination, "depth")


def extract_portrait_matte(source: Path, destination: Path) -> Path | None:
    return _extract_aux(source, destination, "urn_com_apple_photo_2018_aux_portraiteffectsmatte")
