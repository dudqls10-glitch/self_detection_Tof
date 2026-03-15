"""Dataset utilities for RB10 ToF text recordings."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np


PACKAGE_NAME = "self_compention_tof"


@dataclass(slots=True)
class SelfOnlySample:
    """One self-only sample for a single sensor."""

    q: np.ndarray
    tof: float
    sensor_id: int
    valid: bool
    timestamp: str | None = None
    source_file: str | None = None


def default_dataset_dir() -> Path:
    """Return the dataset directory used by this package."""
    candidates = [
        Path(__file__).resolve().parents[1] / "dataset",
        Path.cwd() / "src" / PACKAGE_NAME / "dataset",
        Path.cwd() / PACKAGE_NAME / "dataset",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    try:
        from ament_index_python.packages import get_package_share_directory

        share_dir = Path(get_package_share_directory(PACKAGE_NAME))
        share_dataset_dir = share_dir / "dataset"
        if share_dataset_dir.exists():
            return share_dataset_dir.resolve()
    except Exception:
        pass

    return candidates[0].resolve()


def collect_txt_files(
    dataset_dir: Path | None = None,
    files: Iterable[str | Path] | None = None,
    patterns: Iterable[str] | None = None,
) -> list[Path]:
    """Resolve dataset files from explicit paths or a dataset directory."""
    if files:
        return [Path(file_path).expanduser().resolve() for file_path in files]

    base_dir = (dataset_dir or default_dataset_dir()).expanduser().resolve()
    if patterns:
        matched_files: set[Path] = set()
        for pattern in patterns:
            matched_files.update(base_dir.glob(pattern))
        txt_files = sorted(path.resolve() for path in matched_files if path.is_file())
    else:
        txt_files = sorted(base_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {base_dir}")
    return txt_files


def parse_header(dataset_path: Path) -> list[str]:
    """Parse the '# Data format:' header from a dataset text file."""
    lines = dataset_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# Data format:"):
            header_text = stripped.split(":", 1)[1].strip()
            if not header_text and index + 1 < len(lines):
                next_line = lines[index + 1].strip()
                if next_line.startswith("#"):
                    header_text = next_line.lstrip("#").strip()
            return [part.strip() for part in header_text.split(",")]
    raise ValueError(f"Could not find '# Data format:' header in {dataset_path}")


def load_time_series_dataset(dataset_path: Path) -> list[dict[str, float | str]]:
    """Load one RB10 txt dataset as a row-wise table."""
    header = parse_header(dataset_path)
    rows: list[dict[str, float | str]] = []

    with dataset_path.open("r", encoding="utf-8", newline="") as dataset_file:
        reader = csv.reader(dataset_file, skipinitialspace=True)
        for raw_row in reader:
            if not raw_row:
                continue
            if raw_row[0].strip().startswith("#"):
                continue
            row = [value.strip() for value in raw_row]
            if len(row) != len(header):
                raise ValueError(
                    f"Column count mismatch while reading {dataset_path}: "
                    f"expected {len(header)}, got {len(row)}"
                )

            parsed_row: dict[str, float | str] = {"timestamp": row[0]}
            for column_name, value in zip(header[1:], row[1:]):
                parsed_row[column_name] = float(value)
            rows.append(parsed_row)

    if not rows:
        raise ValueError(f"No data rows found in {dataset_path}")
    return rows


def load_time_seconds(dataset_path: Path) -> tuple[list[float], list[dict[str, float | str]]]:
    """Load time deltas in seconds together with dataset rows."""
    rows = load_time_series_dataset(dataset_path)
    base_time = datetime.fromisoformat(str(rows[0]["timestamp"]))
    time_seconds = [
        (datetime.fromisoformat(str(row["timestamp"])) - base_time).total_seconds()
        for row in rows
    ]
    return time_seconds, rows


def _sensor_ids_from_rows(rows: list[dict[str, float | str]]) -> list[int]:
    sensor_ids = []
    for key in rows[0]:
        if key.startswith("tof") and key[3:].isdigit():
            sensor_ids.append(int(key[3:]))
    if not sensor_ids:
        raise ValueError("No tofN columns found in dataset")
    return sorted(sensor_ids)


def _is_sensor_valid(
    row: dict[str, float | str],
    sensor_id: int,
    min_tof: float | None,
    max_tof: float | None,
) -> bool:
    tof_value = float(row[f"tof{sensor_id}"])
    if not math.isfinite(tof_value):
        return False
    if min_tof is not None and tof_value < min_tof:
        return False
    if max_tof is not None and tof_value > max_tof:
        return False
    return True


def load_self_only_samples(
    dataset_files: Iterable[str | Path],
    sensor_ids: Iterable[int] | None = None,
    min_tof: float | None = 1.0,
    max_tof: float | None = None,
) -> list[SelfOnlySample]:
    """Flatten one or more RB10 datasets into per-sensor self-only samples."""
    samples: list[SelfOnlySample] = []

    for file_path in dataset_files:
        dataset_path = Path(file_path).expanduser().resolve()
        rows = load_time_series_dataset(dataset_path)
        active_sensor_ids = list(sensor_ids) if sensor_ids else _sensor_ids_from_rows(rows)

        for row in rows:
            q = np.asarray([float(row[f"j{joint_id}"]) for joint_id in range(1, 7)])
            for sensor_id in active_sensor_ids:
                tof = float(row[f"tof{sensor_id}"])
                valid = _is_sensor_valid(row, sensor_id, min_tof=min_tof, max_tof=max_tof)
                samples.append(
                    SelfOnlySample(
                        q=q.copy(),
                        tof=tof,
                        sensor_id=sensor_id,
                        valid=valid,
                        timestamp=str(row["timestamp"]),
                        source_file=dataset_path.name,
                    )
                )

    if not samples:
        raise ValueError("No self-only samples were loaded")
    return samples
