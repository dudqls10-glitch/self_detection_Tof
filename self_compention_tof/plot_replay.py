"""Plot replay classifier results from a CSV file."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

from .dataset_io import default_dataset_dir


LABEL_COLORS = {
    "SELF": "#2a9d8f",
    "UNCERTAIN": "#f4a261",
    "EXTERNAL_CANDIDATE": "#e76f51",
    "EXTERNAL_CONFIRMED": "#d62828",
}


def load_replay_csv(csv_path: Path) -> dict[int, list[dict[str, float | str]]]:
    """Load replay results grouped by sensor id."""
    grouped_rows: dict[int, list[dict[str, float | str]]] = defaultdict(list)
    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            sensor_id = int(row["sensor_id"])
            parsed_row: dict[str, float | str] = {
                "timestamp": row["timestamp"],
                "label": row["label"],
                "tof": float(row["tof"]),
                "mu_self": float(row["mu_self"]) if row["mu_self"] else float("nan"),
                "d_low": float(row["d_low"]) if row["d_low"] else float("nan"),
                "d_high": float(row["d_high"]) if row["d_high"] else float("nan"),
                "decision_low": (
                    float(row["decision_low"]) if row.get("decision_low") else float("nan")
                ),
                "q_distance": (
                    float(row["q_distance"]) if row["q_distance"] else float("nan")
                ),
                "lower_break": (
                    float(row["lower_break"]) if row["lower_break"] else float("nan")
                ),
                "upper_break": (
                    float(row["upper_break"]) if row["upper_break"] else float("nan")
                ),
            }
            grouped_rows[sensor_id].append(parsed_row)
    if not grouped_rows:
        raise ValueError(f"No replay rows found in {csv_path}")
    return dict(sorted(grouped_rows.items()))


def _time_seconds(rows: list[dict[str, float | str]]) -> list[float]:
    base_time = datetime.fromisoformat(str(rows[0]["timestamp"]))
    return [
        (datetime.fromisoformat(str(row["timestamp"])) - base_time).total_seconds()
        for row in rows
    ]


def plot_replay_results(
    grouped_rows: dict[int, list[dict[str, float | str]]],
    output_path: Path | None = None,
    show_plot: bool = True,
    title: str | None = None,
) -> None:
    """Plot sensor-wise replay results with self bands and label coloring."""
    sensor_ids = sorted(grouped_rows)
    figure, axes = plt.subplots(
        len(sensor_ids),
        1,
        figsize=(16, max(4.5, 3.2 * len(sensor_ids))),
        sharex=True,
    )
    if len(sensor_ids) == 1:
        axes = [axes]

    if title is None:
        title = "ToF Replay Classification"
    figure.suptitle(title, fontsize=15)

    for axis, sensor_id in zip(axes, sensor_ids):
        rows = grouped_rows[sensor_id]
        time_seconds = _time_seconds(rows)
        tof_values = [float(row["tof"]) for row in rows]
        mu_self = [float(row["mu_self"]) for row in rows]
        d_low = [float(row["d_low"]) for row in rows]
        d_high = [float(row["d_high"]) for row in rows]
        decision_low = [float(row["decision_low"]) for row in rows]

        axis.fill_between(
            time_seconds,
            d_low,
            d_high,
            color="#a8dadc",
            alpha=0.35,
            label="prediction band",
        )
        axis.plot(
            time_seconds,
            decision_low,
            color="#8d99ae",
            linestyle=":",
            linewidth=1.2,
            label="external threshold",
        )
        axis.plot(time_seconds, mu_self, color="#457b9d", linestyle="--", linewidth=1.3,
                  label="mu_self")
        axis.plot(time_seconds, tof_values, color="#264653", linewidth=1.1, label="tof")

        for label, color in LABEL_COLORS.items():
            label_times = [
                time_seconds[index]
                for index, row in enumerate(rows)
                if str(row["label"]) == label
            ]
            label_tof = [
                tof_values[index]
                for index, row in enumerate(rows)
                if str(row["label"]) == label
            ]
            if label_times:
                axis.scatter(
                    label_times,
                    label_tof,
                    s=10,
                    color=color,
                    label=label,
                    alpha=0.85,
                )

        axis.set_ylabel(f"S{sensor_id}\nmm")
        axis.grid(True, alpha=0.25)
        axis.legend(loc="upper right", ncol=5, fontsize=8)

    axes[-1].set_xlabel("Time [s]")
    figure.tight_layout(rect=(0, 0, 1, 0.97))

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=150)
        print(f"Saved plot: {output_path}")

    if show_plot:
        plt.show()
    else:
        plt.close(figure)


def build_parser() -> argparse.ArgumentParser:
    default_dir = default_dataset_dir()
    parser = argparse.ArgumentParser(
        description="Plot replay classifier CSV with self bands and label colors."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=default_dir / "tof_replay.csv",
        help="Replay CSV path. Default: <package dataset>/tof_replay.csv",
    )
    parser.add_argument(
        "--sensor-ids",
        type=int,
        nargs="+",
        default=None,
        help="Optional subset of sensors to plot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_dir / "tof_replay_plot.png",
        help="PNG output path. Default: <package dataset>/tof_replay_plot.png",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Optional figure title.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save the plot without opening a matplotlib window.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    csv_path = args.csv.expanduser().resolve()
    grouped_rows = load_replay_csv(csv_path)
    if args.sensor_ids:
        requested_ids = {int(sensor_id) for sensor_id in args.sensor_ids}
        grouped_rows = {
            sensor_id: rows
            for sensor_id, rows in grouped_rows.items()
            if sensor_id in requested_ids
        }
        if not grouped_rows:
            raise ValueError(f"No requested sensors found in {csv_path}")

    plot_replay_results(
        grouped_rows=grouped_rows,
        output_path=args.output.expanduser().resolve(),
        show_plot=not args.no_show,
        title=args.title or f"Replay Plot - {csv_path.name}",
    )


if __name__ == "__main__":
    main()
