"""ROS2 realtime inference node for ToF self/external classification."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState, Range
from std_msgs.msg import Bool, Int32MultiArray, String

from .dataset_io import default_dataset_dir
from .model import (
    EXTERNAL_CANDIDATE,
    EXTERNAL_CONFIRMED,
    SELF,
    UNCERTAIN,
    classify_all_sensors,
    create_hysteresis_states,
    load_model_json,
)


LABEL_TO_CODE = {
    SELF: 0,
    EXTERNAL_CANDIDATE: 1,
    EXTERNAL_CONFIRMED: 2,
    UNCERTAIN: 3,
}


class ToFSelfRealtimeInferNode(Node):
    """Realtime self/external classifier using JointState and ToF Range topics."""

    def __init__(self) -> None:
        super().__init__("tof_self_realtime_infer")

        default_model_path = default_dataset_dir() / "tof_self_model.json"

        self.declare_parameter("model_path", str(default_model_path))
        self.declare_parameter("joint_state_topic", "/joint_states")
        self.declare_parameter("tof_topic_prefix", "/tof_distance")
        self.declare_parameter("sensor_ids", [3, 4, 6, 7])
        self.declare_parameter(
            "joint_names",
            ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"],
        )
        self.declare_parameter("q_use_dims", [])
        self.declare_parameter("q_query_radius", 5.0)
        self.declare_parameter("ext_margin", 20.0)
        self.declare_parameter("self_margin", 0.0)
        self.declare_parameter("n_on", 3)
        self.declare_parameter("n_off", 3)
        self.declare_parameter("publish_rate_hz", 30.0)
        self.declare_parameter("publish_external_detected", True)
        self.declare_parameter("publish_label_codes", False)
        self.declare_parameter("publish_result_json", False)

        self.model_path = Path(self.get_parameter("model_path").value).expanduser().resolve()
        self.joint_state_topic = str(self.get_parameter("joint_state_topic").value)
        self.tof_topic_prefix = str(self.get_parameter("tof_topic_prefix").value)
        self.sensor_ids = [int(value) for value in self.get_parameter("sensor_ids").value]
        self.joint_names = [str(value) for value in self.get_parameter("joint_names").value]
        self.q_query_radius = float(self.get_parameter("q_query_radius").value)
        self.ext_margin = float(self.get_parameter("ext_margin").value)
        self.self_margin = float(self.get_parameter("self_margin").value)
        self.n_on = int(self.get_parameter("n_on").value)
        self.n_off = int(self.get_parameter("n_off").value)
        publish_rate_hz = float(self.get_parameter("publish_rate_hz").value)
        self.publish_external_detected = bool(
            self.get_parameter("publish_external_detected").value
        )
        self.publish_label_codes = bool(self.get_parameter("publish_label_codes").value)
        self.publish_result_json = bool(self.get_parameter("publish_result_json").value)

        metadata, self.model = load_model_json(self.model_path)
        model_q_dims = metadata.get("q_use_dims_zero_based", [1, 2, 3])
        requested_q_dims = self.get_parameter("q_use_dims").value
        self.q_use_dims = requested_q_dims if requested_q_dims else model_q_dims

        self.states = create_hysteresis_states(self.sensor_ids)
        self.latest_joint_positions_deg: np.ndarray | None = None
        self.latest_tof: dict[int, float] = {}

        self.external_pub = (
            self.create_publisher(Bool, "/tof_self_classifier/external_detected", 10)
            if self.publish_external_detected
            else None
        )
        self.label_codes_pub = (
            self.create_publisher(Int32MultiArray, "/tof_self_classifier/label_codes", 10)
            if self.publish_label_codes
            else None
        )
        self.result_json_pub = (
            self.create_publisher(String, "/tof_self_classifier/result_json", 10)
            if self.publish_result_json
            else None
        )

        self.create_subscription(
            JointState, self.joint_state_topic, self.joint_callback, 10
        )
        self.tof_subscriptions = [
            self.create_subscription(
                Range,
                f"{self.tof_topic_prefix}{sensor_id}",
                lambda msg, sid=sensor_id: self.tof_callback(msg, sid),
                10,
            )
            for sensor_id in self.sensor_ids
        ]

        timer_period = 1.0 / publish_rate_hz if publish_rate_hz > 0.0 else 0.05
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().info(f"Loaded model: {self.model_path}")
        self.get_logger().info(f"Model sensors: {self.sensor_ids}")
        self.get_logger().info(f"Using q dims: {self.q_use_dims}")
        self.get_logger().info(f"Joint topic: {self.joint_state_topic}")
        self.get_logger().info(
            f"ToF topics: {[f'{self.tof_topic_prefix}{sensor_id}' for sensor_id in self.sensor_ids]}"
        )
        enabled_publishers = []
        if self.publish_external_detected:
            enabled_publishers.append("/tof_self_classifier/external_detected")
        if self.publish_label_codes:
            enabled_publishers.append("/tof_self_classifier/label_codes")
        if self.publish_result_json:
            enabled_publishers.append("/tof_self_classifier/result_json")
        self.get_logger().info(f"Enabled publishers: {enabled_publishers}")

    def joint_callback(self, msg: JointState) -> None:
        """Read JointState in radians and convert to degrees in a fixed order."""
        name_to_index = {name: index for index, name in enumerate(msg.name)}
        positions_rad: list[float] = []

        for joint_name in self.joint_names:
            if joint_name not in name_to_index:
                self.get_logger().warn(
                    f"Joint '{joint_name}' not found in JointState. Available: {msg.name}",
                    throttle_duration_sec=5.0,
                )
                return
            positions_rad.append(float(msg.position[name_to_index[joint_name]]))

        self.latest_joint_positions_deg = np.rad2deg(
            np.asarray(positions_rad, dtype=float)
        )

    def tof_callback(self, msg: Range, sensor_id: int) -> None:
        """Store latest ToF distance for one sensor."""
        self.latest_tof[sensor_id] = float(msg.range)

    def timer_callback(self) -> None:
        """Run realtime classification when all required inputs are available."""
        if self.latest_joint_positions_deg is None:
            return
        if any(sensor_id not in self.latest_tof for sensor_id in self.sensor_ids):
            return

        results = classify_all_sensors(
            q_now=self.latest_joint_positions_deg,
            tof_measurements=self.latest_tof,
            model=self.model,
            states=self.states,
            q_use_dims=self.q_use_dims,
            q_query_radius=self.q_query_radius,
            ext_margin=self.ext_margin,
            self_margin=self.self_margin,
            n_on=self.n_on,
            n_off=self.n_off,
            sensor_ids=self.sensor_ids,
        )

        external_detected = any(
            result["label"] in {EXTERNAL_CANDIDATE, EXTERNAL_CONFIRMED}
            for result in results.values()
        )
        if self.external_pub is not None:
            self.external_pub.publish(Bool(data=external_detected))

        if self.label_codes_pub is not None:
            label_codes_msg = Int32MultiArray()
            label_codes_msg.data = [
                LABEL_TO_CODE[results[sensor_id]["label"]] for sensor_id in self.sensor_ids
            ]
            self.label_codes_pub.publish(label_codes_msg)

        if self.result_json_pub is not None:
            payload = {
                "sensor_ids": self.sensor_ids,
                "joint_positions_deg": self.latest_joint_positions_deg.tolist(),
                "external_detected": external_detected,
                "results": {
                    str(sensor_id): {
                        "tof": self.latest_tof[sensor_id],
                        "label": results[sensor_id]["label"],
                        "info": results[sensor_id]["info"],
                    }
                    for sensor_id in self.sensor_ids
                },
            }
            self.result_json_pub.publish(String(data=json.dumps(payload)))


def main() -> None:
    rclpy.init()
    node = ToFSelfRealtimeInferNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
