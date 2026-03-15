"""Offline model building and online ToF self/external classification."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import t as student_t


SELF = "SELF"
EXTERNAL_CANDIDATE = "EXTERNAL_CANDIDATE"
EXTERNAL_CONFIRMED = "EXTERNAL_CONFIRMED"
UNCERTAIN = "UNCERTAIN"


@dataclass(slots=True)
class HysteresisState:
    """Temporal state used by the online classifier."""

    prev_label: str = SELF
    ext_counter: int = 0
    self_counter: int = 0


@dataclass(slots=True)
class ReferenceEntry:
    """Self-reference statistics for one support region."""

    q_center: list[float]
    mu_self: float
    std_self: float
    n_samples: int
    d_low: float
    d_high: float
    support_radius: float


def normalize_q_use_dims(q_use_dims: list[int | str] | tuple[int | str, ...]) -> list[int]:
    """Normalize user joint selections to zero-based joint indices."""
    if not q_use_dims:
        raise ValueError("q_use_dims must not be empty")

    if any(isinstance(item, str) for item in q_use_dims):
        normalized = []
        for item in q_use_dims:
            if not isinstance(item, str):
                normalized.append(int(item))
                continue
            label = item.strip().lower()
            if label.isdigit():
                normalized.append(int(label) - 1)
                continue
            if label.startswith(("q", "j")) and label[1:].isdigit():
                normalized.append(int(label[1:]) - 1)
                continue
            raise ValueError(f"Unsupported joint label: {item}")
        return _validate_joint_dims(normalized)

    dims = [int(item) for item in q_use_dims]
    if any(value == 0 for value in dims):
        return _validate_joint_dims(dims)
    if all(1 <= value <= 6 for value in dims):
        return _validate_joint_dims([value - 1 for value in dims])
    return _validate_joint_dims(dims)


def _validate_joint_dims(joint_dims: list[int]) -> list[int]:
    for dim in joint_dims:
        if dim < 0 or dim >= 6:
            raise ValueError(f"Joint dimension out of range: {dim}")
    return joint_dims


def _select_dims(q: np.ndarray, q_use_dims: list[int]) -> np.ndarray:
    return np.asarray(q, dtype=float)[q_use_dims]


def _normalize_resolution(
    grid_resolution: float | list[float] | tuple[float, ...],
    ndim: int,
) -> np.ndarray:
    if isinstance(grid_resolution, (int, float)):
        resolution = np.full(ndim, float(grid_resolution))
    else:
        resolution = np.asarray(grid_resolution, dtype=float)
        if resolution.shape != (ndim,):
            raise ValueError(
                f"grid_resolution must have {ndim} values, got {resolution.shape}"
            )
    if np.any(resolution <= 0.0):
        raise ValueError("grid_resolution must be positive")
    return resolution


def _group_by_grid_cell(
    data: list[tuple[np.ndarray, float]],
    grid_resolution: float | list[float] | tuple[float, ...],
) -> list[list[tuple[np.ndarray, float]]]:
    if not data:
        return []
    resolution = _normalize_resolution(grid_resolution, data[0][0].shape[0])
    groups: dict[tuple[int, ...], list[tuple[np.ndarray, float]]] = {}
    for q_red, tof in data:
        cell = tuple(np.floor(np.asarray(q_red) / resolution).astype(int).tolist())
        groups.setdefault(cell, []).append((q_red, tof))
    return [groups[key] for key in sorted(groups)]


def _build_reference_groups(
    data: list[tuple[np.ndarray, float]],
    support_margin: float,
) -> list[list[tuple[np.ndarray, float]]]:
    if not data:
        return []
    if support_margin <= 0.0:
        raise ValueError("support_margin must be positive for knn_reference")

    q_matrix = np.asarray([item[0] for item in data], dtype=float)
    tree = cKDTree(q_matrix)
    assigned = np.zeros(len(data), dtype=bool)
    groups: list[list[tuple[np.ndarray, float]]] = []
    for center_index in range(len(data)):
        if assigned[center_index]:
            continue
        member_indices = tree.query_ball_point(q_matrix[center_index], support_margin)
        member_indices = [
            member_index for member_index in member_indices if not assigned[member_index]
        ]
        if not member_indices:
            continue
        groups.append([data[member_index] for member_index in member_indices])
        assigned[np.asarray(member_indices, dtype=int)] = True
    return groups


def _compute_prediction_interval(
    mean_value: float,
    std_value: float,
    sample_count: int,
    alpha: float,
) -> tuple[float, float]:
    # Prediction interval for one future scalar ToF observation using
    # self-only samples from the local joint-state neighborhood.
    if sample_count <= 1 or std_value == 0.0:
        return mean_value, mean_value

    t_value = float(student_t.ppf(1.0 - alpha / 2.0, df=sample_count - 1))
    half_band = t_value * std_value * math.sqrt(1.0 + 1.0 / sample_count)
    return mean_value - half_band, mean_value + half_band


def build_tof_self_model(
    self_only_dataset: list[Any],
    q_use_dims: list[int | str] | tuple[int | str, ...],
    method: str = "grid",
    grid_resolution: float | list[float] | tuple[float, ...] = 5.0,
    min_samples: int = 20,
    alpha: float = 0.05,
    support_margin: float = 5.0,
) -> dict[int, list[dict[str, Any]]]:
    """Build a per-sensor self-reference model from self-only samples."""
    if min_samples < 2:
        raise ValueError("min_samples must be at least 2")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")

    joint_dims = normalize_q_use_dims(list(q_use_dims))
    sensor_ids = sorted({int(sample.sensor_id) for sample in self_only_dataset})
    model: dict[int, list[dict[str, Any]]] = {}

    for sensor_id in sensor_ids:
        filtered_data: list[tuple[np.ndarray, float]] = []
        for sample in self_only_dataset:
            if int(sample.sensor_id) != sensor_id or not bool(sample.valid):
                continue
            q_reduced = _select_dims(np.asarray(sample.q, dtype=float), joint_dims)
            filtered_data.append((q_reduced, float(sample.tof)))

        if method == "grid":
            groups = _group_by_grid_cell(filtered_data, grid_resolution)
        elif method == "knn_reference":
            groups = _build_reference_groups(filtered_data, support_margin=support_margin)
        else:
            raise ValueError(f"Unsupported method: {method}")

        sensor_entries: list[dict[str, Any]] = []
        for group in groups:
            if len(group) < min_samples:
                continue

            q_values = np.asarray([item[0] for item in group], dtype=float)
            tof_values = np.asarray([item[1] for item in group], dtype=float)

            q_center = np.mean(q_values, axis=0)
            mu_self = float(np.mean(tof_values))
            std_self = float(np.std(tof_values, ddof=1)) if len(tof_values) > 1 else 0.0
            n_samples = int(len(tof_values))
            d_low, d_high = _compute_prediction_interval(
                mean_value=mu_self,
                std_value=std_self,
                sample_count=n_samples,
                alpha=alpha,
            )

            support_radius = float(
                min(
                    support_margin,
                    np.max(np.linalg.norm(q_values - q_center, axis=1)),
                )
            )
            entry = ReferenceEntry(
                q_center=q_center.astype(float).tolist(),
                mu_self=mu_self,
                std_self=std_self,
                n_samples=n_samples,
                d_low=float(d_low),
                d_high=float(d_high),
                support_radius=support_radius,
            )
            sensor_entries.append(asdict(entry))

        model[sensor_id] = sensor_entries

    return model


def find_nearest_reference(
    q_red: np.ndarray,
    sensor_entries: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    """Return the nearest reference entry and its joint-space distance."""
    if not sensor_entries:
        return None, math.inf

    centers = np.asarray([entry["q_center"] for entry in sensor_entries], dtype=float)
    distances = np.linalg.norm(centers - q_red, axis=1)
    nearest_index = int(np.argmin(distances))
    return sensor_entries[nearest_index], float(distances[nearest_index])


def classify_tof(
    q_now: np.ndarray | list[float],
    tof_now: float,
    sensor_id: int,
    model: dict[int, list[dict[str, Any]]],
    q_use_dims: list[int | str] | tuple[int | str, ...],
    hysteresis_state: HysteresisState,
    q_query_radius: float,
    ext_margin: float,
    self_margin: float,
    n_on: int,
    n_off: int,
) -> tuple[str, dict[str, Any] | None]:
    """Classify one ToF value using a lower-bound self reference.

    For ToF distance, the main external cue is a lower-side break:
    a closer object produces a smaller-than-expected distance.
    Runtime decision is intentionally simple:
    - outside support -> UNCERTAIN
    - below the lower threshold -> EXTERNAL candidate
    - otherwise -> SELF
    """
    joint_dims = normalize_q_use_dims(list(q_use_dims))
    q_reduced = _select_dims(np.asarray(q_now, dtype=float), joint_dims)
    sensor_entries = model.get(int(sensor_id), [])
    nearest_entry, q_distance = find_nearest_reference(q_reduced, sensor_entries)

    if nearest_entry is None:
        return UNCERTAIN, None

    if q_distance > q_query_radius:
        return UNCERTAIN, {
            "q_center": nearest_entry["q_center"],
            "reason": "outside_support",
            "q_distance": q_distance,
        }

    mu_self = float(nearest_entry["mu_self"])
    d_low = float(nearest_entry["d_low"])
    d_high = float(nearest_entry["d_high"])
    lower_break = d_low - float(tof_now)
    upper_break = float(tof_now) - d_high
    decision_low = d_low - ext_margin

    # Lower-bound-only decision:
    # - if the measured distance is much smaller than the learned self-only
    #   lower bound, treat it as an external-object cue
    # - otherwise keep the label as SELF while staying inside support
    if tof_now < decision_low:
        instant_label = EXTERNAL_CANDIDATE
    else:
        instant_label = SELF

    if instant_label == EXTERNAL_CANDIDATE:
        hysteresis_state.ext_counter += 1
        hysteresis_state.self_counter = 0
        if hysteresis_state.ext_counter >= n_on:
            final_label = EXTERNAL_CONFIRMED
        else:
            final_label = EXTERNAL_CANDIDATE
    elif instant_label == SELF:
        hysteresis_state.self_counter += 1
        hysteresis_state.ext_counter = 0
        if hysteresis_state.self_counter >= n_off:
            final_label = SELF
        else:
            final_label = hysteresis_state.prev_label
    else:
        hysteresis_state.ext_counter = 0
        hysteresis_state.self_counter = 0
        final_label = UNCERTAIN

    hysteresis_state.prev_label = final_label
    info = {
        "q_center": nearest_entry["q_center"],
        "mu_self": mu_self,
        "d_low": d_low,
        "d_high": d_high,
        "decision_low": decision_low,
        "self_margin": self_margin,
        "deviation_score": {
            "lower_break": lower_break,
            "upper_break": upper_break,
            "q_distance": q_distance,
        },
    }
    return final_label, info


def classify_all_sensors(
    q_now: np.ndarray | list[float],
    tof_measurements: dict[int, float] | dict[str, float],
    model: dict[int, list[dict[str, Any]]],
    states: dict[int, HysteresisState],
    q_use_dims: list[int | str] | tuple[int | str, ...],
    q_query_radius: float,
    ext_margin: float,
    self_margin: float,
    n_on: int,
    n_off: int,
    sensor_ids: list[int] | tuple[int, ...] | None = None,
) -> dict[int, dict[str, Any]]:
    """Run the classifier for multiple sensors at the current frame."""
    active_sensor_ids = (
        list(sensor_ids) if sensor_ids else sorted(int(sensor_id) for sensor_id in model)
    )
    results: dict[int, dict[str, Any]] = {}

    for sensor_id in active_sensor_ids:
        tof_value = tof_measurements.get(sensor_id, tof_measurements.get(str(sensor_id)))
        if tof_value is None:
            results[sensor_id] = {"label": UNCERTAIN, "info": {"reason": "missing_tof"}}
            continue
        label, info = classify_tof(
            q_now=q_now,
            tof_now=float(tof_value),
            sensor_id=sensor_id,
            model=model,
            q_use_dims=q_use_dims,
            hysteresis_state=states[sensor_id],
            q_query_radius=q_query_radius,
            ext_margin=ext_margin,
            self_margin=self_margin,
            n_on=n_on,
            n_off=n_off,
        )
        results[sensor_id] = {"label": label, "info": info}

    return results


def create_hysteresis_states(
    sensor_ids: list[int] | tuple[int, ...],
    prev_label: str = SELF,
) -> dict[int, HysteresisState]:
    """Create default hysteresis states for the requested sensors."""
    return {int(sensor_id): HysteresisState(prev_label=prev_label) for sensor_id in sensor_ids}


def save_model_json(
    output_path: str | Path,
    model: dict[int, list[dict[str, Any]]],
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Save a built model to JSON."""
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata or {},
        "model": {str(sensor_id): entries for sensor_id, entries in sorted(model.items())},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_model_json(model_path: str | Path) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    """Load a saved model JSON file."""
    path = Path(model_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    model = {int(sensor_id): entries for sensor_id, entries in payload["model"].items()}
    return payload.get("metadata", {}), model
