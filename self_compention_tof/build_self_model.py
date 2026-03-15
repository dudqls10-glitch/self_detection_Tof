"""CLI for building a ToF self-reference model from dataset text files."""

from __future__ import annotations

import argparse
from pathlib import Path

from .dataset_io import collect_txt_files, default_dataset_dir, load_self_only_samples
from .model import build_tof_self_model, normalize_q_use_dims, save_model_json


def _parse_sensor_ids(values: list[int] | None) -> list[int] | None:
    if not values:
        return None
    return sorted({int(value) for value in values})


def build_parser() -> argparse.ArgumentParser:
    default_dir = default_dataset_dir()
    parser = argparse.ArgumentParser(
        description="Build a ToF self-reference model from RB10 self-only txt datasets."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=default_dir,
        help="Directory containing txt datasets. Default: ./dataset inside the package.",
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=[],
        help="Specific txt file to include. Can be passed multiple times.",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Glob pattern inside --dataset-dir, e.g. '*new.txt' or '[1]*.txt'. Can be passed multiple times.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Use all txt files in --dataset-dir. This is also the default when --file and --pattern are omitted.",
    )
    parser.add_argument(
        "--sensor-ids",
        type=int,
        nargs="+",
        default=None,
        help="Sensor IDs to build. Default: use every tofN column found in the files.",
    )
    parser.add_argument(
        "--q-use-dims",
        nargs="+",
        default=["q2", "q3", "q4"],
        help="Joint dimensions to use, e.g. q2 q3 q4 or 2 3 4.",
    )
    # method / grid_resolution:
    # - grid: joint space를 bin으로 나눠 local self reference 생성
    # - knn_reference: support_margin 반경 기준으로 local reference 생성
    parser.add_argument(
        "--method",
        choices=["grid", "knn_reference"],
        default="grid",
        help="Reference grouping strategy.",
    )
    parser.add_argument(
        "--grid-resolution",
        type=float,
        nargs="+",
        default=[5.0, 5.0, 5.0],
        help="Grid bin size per selected joint in degrees.",
    )
    # min_samples:
    # 한 reference entry를 만들기 위한 최소 샘플 수.
    # 너무 크면 reference 수가 줄고, coverage 부족으로 uncertain이 늘 수 있다.
    parser.add_argument(
        "--min-samples",
        type=int,
        default=20,
        help="Minimum sample count per reference entry.",
    )
    # alpha:
    # Student-t prediction interval의 유의수준.
    # 작게 할수록 d_low ~ d_high band가 넓어져 self 판정이 쉬워진다.
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        help="Significance level for the prediction interval.",
    )
    # support_margin:
    # knn_reference일 때 reference를 묶는 반경이고,
    # 저장되는 support_radius의 기본 상한 역할도 한다.
    parser.add_argument(
        "--support-margin",
        type=float,
        default=5.0,
        help="Support radius in joint space for knn_reference and stored support info.",
    )
    # min_tof / max_tof:
    # txt 원본에 valid 플래그가 없어서, 현재는 ToF 값 범위로 유효 샘플을 거른다.
    parser.add_argument(
        "--min-tof",
        type=float,
        default=1.0,
        help="Minimum valid ToF value in mm.",
    )
    parser.add_argument(
        "--max-tof",
        type=float,
        default=None,
        help="Maximum valid ToF value in mm.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_dir / "tof_self_model.json",
        help="Where to save the model JSON. Default: <package dataset>/tof_self_model.json",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    print("Starting ToF self-model build...", flush=True)
    dataset_files = collect_txt_files(
        dataset_dir=args.dataset_dir,
        files=args.files,
        patterns=args.pattern if not args.files else None,
    )
    sensor_ids = _parse_sensor_ids(args.sensor_ids)
    q_use_dims = normalize_q_use_dims(args.q_use_dims)
    grid_resolution = (
        args.grid_resolution[0]
        if len(args.grid_resolution) == 1
        else [float(value) for value in args.grid_resolution]
    )

    samples = load_self_only_samples(
        dataset_files=dataset_files,
        sensor_ids=sensor_ids,
        min_tof=args.min_tof,
        max_tof=args.max_tof,
    )
    model = build_tof_self_model(
        self_only_dataset=samples,
        q_use_dims=q_use_dims,
        method=args.method,
        grid_resolution=grid_resolution,
        min_samples=args.min_samples,
        alpha=args.alpha,
        support_margin=args.support_margin,
    )

    output_path = args.output.expanduser().resolve()
    metadata = {
        "dataset_files": [str(path) for path in dataset_files],
        "sensor_ids": sensor_ids or sorted(model),
        "q_use_dims_zero_based": q_use_dims,
        "method": args.method,
        "grid_resolution": grid_resolution,
        "min_samples": args.min_samples,
        "alpha": args.alpha,
        "support_margin": args.support_margin,
        "min_tof": args.min_tof,
        "max_tof": args.max_tof,
    }
    saved_path = save_model_json(output_path=output_path, model=model, metadata=metadata)

    print(f"Using {len(dataset_files)} dataset file(s):", flush=True)
    for dataset_file in dataset_files:
        print(f"  - {dataset_file}", flush=True)
    print(f"Saved model: {saved_path}", flush=True)
    for sensor_id in sorted(model):
        print(
            f"sensor {sensor_id}: {len(model[sensor_id])} reference entries "
            f"from {sum(entry['n_samples'] for entry in model[sensor_id])} grouped samples",
            flush=True,
        )
    print("ToF self-model build completed.", flush=True)


if __name__ == "__main__":
    main()
