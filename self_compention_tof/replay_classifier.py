"""CLI for replaying the ToF classifier on a dataset text file."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .dataset_io import collect_txt_files, default_dataset_dir, load_time_series_dataset
from .model import classify_all_sensors, create_hysteresis_states, load_model_json


def build_parser() -> argparse.ArgumentParser:
    default_dir = default_dataset_dir()
    parser = argparse.ArgumentParser(
        description="Replay the online ToF self/external classifier on a txt dataset."
    )
    parser.add_argument(
        "--model",
        type=Path,
        required=True,
        help="Path to a model JSON file produced by build_tof_self_model.",
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=default_dir,
        help="Directory containing txt datasets when --file is not used.",
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=[],
        help="Specific txt file to replay. Only the first resolved file is used.",
    )
    parser.add_argument(
        "--sensor-ids",
        type=int,
        nargs="+",
        default=None,
        help="Sensor IDs to replay. Default: model sensors.",
    )
    parser.add_argument(
        "--q-use-dims",
        nargs="+",
        default=None,
        help="Override q_use_dims from the model metadata.",
    )
    # q_query_radius:
    # 현재 joint 상태가 가장 가까운 reference center에서 너무 멀면
    # 그 자세는 학습 support 밖으로 보고 uncertain 처리한다.
    parser.add_argument(
        "--q-query-radius",
        type=float,
        default=5.0,
        help="Maximum joint-space distance to the nearest reference.",
    )
    # ext_margin:
    # d_low보다 얼마나 더 작아야 external 후보로 볼지 정하는 값.
    # 크게 하면 external 오탐이 줄고, 작게 하면 더 민감하게 잡는다.
    parser.add_argument(
        "--ext-margin",
        type=float,
        default=20.0,
        help="Extra lower margin to flag an external candidate.",
    )
    # self_margin:
    # lower-bound-only 분류에서는 현재 직접 쓰지 않는다.
    # 인자 호환성을 위해 남겨두고, 필요하면 이후 band 기반 모드로 되돌릴 수 있다.
    parser.add_argument(
        "--self-margin",
        type=float,
        default=0.0,
        help="Margin used for stable self classification.",
    )
    # n_on / n_off:
    # 프레임 단위 debounce.
    # n_on은 external 확정까지 필요한 연속 프레임 수,
    # n_off는 다시 self로 복귀하기 위한 연속 프레임 수다.
    parser.add_argument(
        "--n-on",
        type=int,
        default=3,
        help="Frames needed to confirm an external object.",
    )
    parser.add_argument(
        "--n-off",
        type=int,
        default=3,
        help="Frames needed to return to self.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of rows to print to stdout.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=default_dir / "tof_replay.csv",
        help="Where to save the full replay result CSV. Default: <package dataset>/tof_replay.csv",
    )
    return parser


def _write_results(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    print("Starting ToF replay classification...", flush=True)
    metadata, model = load_model_json(args.model)
    dataset_file = collect_txt_files(dataset_dir=args.dataset_dir, files=args.files)[0]
    rows = load_time_series_dataset(dataset_file)
    sensor_ids = args.sensor_ids or sorted(model)
    q_use_dims = args.q_use_dims or metadata.get("q_use_dims_zero_based", [1, 2])
    states = create_hysteresis_states(sensor_ids)

    replay_rows: list[dict[str, object]] = []
    for row in rows:
        q_now = [float(row[f"j{joint_id}"]) for joint_id in range(1, 7)]
        tof_measurements = {
            sensor_id: float(row[f"tof{sensor_id}"])
            for sensor_id in sensor_ids
            if f"tof{sensor_id}" in row
        }
        results = classify_all_sensors(
            q_now=q_now,
            tof_measurements=tof_measurements,
            model=model,
            states=states,
            q_use_dims=q_use_dims,
            q_query_radius=args.q_query_radius,
            ext_margin=args.ext_margin,
            self_margin=args.self_margin,
            n_on=args.n_on,
            n_off=args.n_off,
            sensor_ids=sensor_ids,
        )

        for sensor_id in sensor_ids:
            info = results[sensor_id]["info"] or {}
            deviation = info.get("deviation_score", {})
            replay_rows.append(
                {
                    "timestamp": row["timestamp"],
                    "sensor_id": sensor_id,
                    "tof": float(row[f"tof{sensor_id}"]),
                    "label": results[sensor_id]["label"],
                    "mu_self": info.get("mu_self"),
                    "d_low": info.get("d_low"),
                    "d_high": info.get("d_high"),
                    "decision_low": info.get("decision_low"),
                    "q_distance": deviation.get("q_distance"),
                    "lower_break": deviation.get("lower_break"),
                    "upper_break": deviation.get("upper_break"),
                }
            )

    for replay_row in replay_rows[: args.limit]:
        print(
            f"{replay_row['timestamp']} sensor={replay_row['sensor_id']} "
            f"tof={replay_row['tof']:.1f} label={replay_row['label']} "
            f"qdist={replay_row['q_distance']}",
            flush=True,
        )

    output_path = args.output_csv.expanduser().resolve()
    _write_results(output_path, replay_rows)
    print(f"Saved replay CSV: {output_path}", flush=True)
    print("ToF replay classification completed.", flush=True)


if __name__ == "__main__":
    main()
