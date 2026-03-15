from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt


SENSOR_GROUPS = {
    "prox_distance": [f"prox{i}" for i in range(1, 9)],
    "tof_distance": [f"tof{i}" for i in range(1, 9)],
    "raw_distance": [f"raw{i}" for i in range(1, 9)],
}

GROUP_TITLES = {
    "prox_distance": "Proximity Distance",
    "tof_distance": "ToF Distance",
    "raw_distance": "Raw Distance",
}


def default_dataset_dir() -> Path:
    home_dataset = Path.home() / "dataset"
    if home_dataset.exists():
        return home_dataset
    return Path(__file__).resolve().parents[1] / "dataset"


def parse_header(dataset_path: Path) -> list[str]:
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


def load_dataset(dataset_path: Path) -> tuple[list[float], dict[str, list[float]]]:
    header = parse_header(dataset_path)
    rows: list[list[str]] = []

    with dataset_path.open("r", encoding="utf-8", newline="") as dataset_file:
        reader = csv.reader(dataset_file, skipinitialspace=True)
        for row in reader:
            if not row:
                continue
            if row[0].strip().startswith("#"):
                continue
            rows.append([value.strip() for value in row])

    if not rows:
        raise ValueError(f"No data rows found in {dataset_path}")

    if any(len(row) != len(header) for row in rows):
        raise ValueError(f"Column count mismatch while reading {dataset_path}")

    base_time = datetime.fromisoformat(rows[0][0])
    time_seconds = [
        (datetime.fromisoformat(row[0]) - base_time).total_seconds() for row in rows
    ]

    data: dict[str, list[float]] = {}
    for column_index, column_name in enumerate(header[1:], start=1):
        data[column_name] = [float(row[column_index]) for row in rows]

    return time_seconds, data


def plot_group(
    dataset_path: Path,
    group_name: str,
    time_seconds: list[float],
    data: dict[str, list[float]],
    save_dir: Path | None,
) -> None:
    columns = SENSOR_GROUPS[group_name]
    missing_columns = [column for column in columns if column not in data]
    if missing_columns:
        raise ValueError(
            f"Missing columns in {dataset_path.name}: {', '.join(missing_columns)}"
        )

    fig, axes = plt.subplots(2, 4, figsize=(18, 8), sharex=True)
    fig.suptitle(f"{dataset_path.name} - {GROUP_TITLES[group_name]}", fontsize=14)

    for index, column_name in enumerate(columns):
        axis = axes[index // 4][index % 4]
        axis.plot(time_seconds, data[column_name], linewidth=1.0)
        axis.set_title(column_name)
        axis.set_xlabel("Time [s]")
        axis.set_ylabel("Distance [mm]")
        axis.grid(True, alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.96))

    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
        output_path = save_dir / f"{dataset_path.stem}_{group_name}.png"
        fig.savefig(output_path, dpi=150)


def collect_txt_files(dataset_dir: Path, files: list[str], plot_all: bool) -> list[Path]:
    if files:
        return [Path(file_path).expanduser().resolve() for file_path in files]

    txt_files = sorted(dataset_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in {dataset_dir}")

    if plot_all:
        return txt_files

    return [txt_files[0]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot prox/raw/tof distances from RB10 txt dataset files."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=default_dataset_dir(),
        help="Directory containing txt datasets. Default: ~/dataset or ./dataset",
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=[],
        help="Specific txt file to plot. Can be passed multiple times.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Plot all txt files in the dataset directory when --file is not used.",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=None,
        help="Optional directory to save PNG files.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Create plots without opening matplotlib windows.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dataset_dir = args.dataset_dir.expanduser().resolve()
    files_to_plot = collect_txt_files(dataset_dir, args.files, args.all)

    print(f"Using dataset directory: {dataset_dir}")
    for dataset_path in files_to_plot:
        time_seconds, data = load_dataset(dataset_path)
        print(f"Plotting: {dataset_path}")
        for group_name in SENSOR_GROUPS:
            plot_group(dataset_path, group_name, time_seconds, data, args.save_dir)

    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
