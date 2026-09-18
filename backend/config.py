"""Application configuration loaded from ~/.config/no_waste_album/config.yaml."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    library: Path
    data_dir: Path
    ml_data_dir: Path
    ml_negative_samples_dir: Path
    host: str = "127.0.0.1"
    port: int = 7008


def load(path: Path | None = None) -> Config:
    path = path or Path.home() / ".config" / "no_waste_album" / "config.yaml"
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip("'\"")
    if not values.get("library"):
        raise ValueError(f"library is required in {path}")
    library = Path(values["library"]).expanduser()
    data_dir = Path(values.get("data_dir", str(library / "no_waste_album"))).expanduser()
    ml_data_dir = Path(values.get("ml_data_dir", str(data_dir / "ML"))).expanduser()
    negative_dir = Path(values.get("ml_negative_samples_dir", str(ml_data_dir / "negative_samples"))).expanduser()
    return Config(library, data_dir, ml_data_dir, negative_dir, values.get("host", "127.0.0.1"), int(values.get("port", "7008")))
