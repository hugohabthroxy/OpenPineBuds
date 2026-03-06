"""
Experiment: Compare Threshold vs FSM cueing control strategies.

Replays recorded FoG probability traces through both control strategies
and compares:
- Detection-to-cue latency (from threshold crossing to command emission)
- False positive rate (cueing events that don't overlap ground truth)
- Total cue duration (how long the patient is cued)
- Number of cue events

Usage:
    python experiment_compare_strategies.py --data fog_trace.csv
                                            [--output results/]

Input CSV format:
    timestamp_s, fog_probability, ground_truth_fog
    0.000, 0.05, 0
    0.033, 0.08, 0
    ...
    5.200, 0.82, 1
"""

import argparse
import csv
import json
import logging
import os
import statistics
import time
from dataclasses import dataclass
from typing import Optional

from cueing_fsm import CueingFSM, CueState, ThresholdConfig, FSMConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TracePoint:
    timestamp_s: float
    fog_probability: float
    ground_truth: bool


def load_trace(csv_path: str) -> list[TracePoint]:
    """Load a FoG probability trace from CSV."""
    points = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            points.append(TracePoint(
                timestamp_s=float(row["timestamp_s"]),
                fog_probability=float(row["fog_probability"]),
                ground_truth=bool(int(row.get("ground_truth_fog",
                                               row.get("ground_truth", "0")))),
            ))
    return points


def extract_gt_intervals(trace: list[TracePoint]) -> list[tuple]:
    """Extract ground-truth FoG intervals as [(start, end), ...]."""
    intervals = []
    in_fog = False
    fog_start = 0.0

    for pt in trace:
        if pt.ground_truth and not in_fog:
            in_fog = True
            fog_start = pt.timestamp_s
        elif not pt.ground_truth and in_fog:
            in_fog = False
            intervals.append((fog_start, pt.timestamp_s))

    if in_fog:
        intervals.append((fog_start, trace[-1].timestamp_s))

    return intervals


def compute_detection_latencies(events, gt_intervals) -> list[float]:
    """For each FoG interval, compute time from GT start to first cue."""
    latencies = []
    for gt_start, gt_end in gt_intervals:
        earliest_cue = None
        for ev in events:
            if ev.start_time >= gt_start and ev.start_time <= gt_end:
                if earliest_cue is None or ev.start_time < earliest_cue:
                    earliest_cue = ev.start_time
        if earliest_cue is not None:
            latencies.append(earliest_cue - gt_start)
    return latencies


import asyncio


async def run_strategy(name: str, fsm: CueingFSM,
                       trace: list[TracePoint]) -> dict:
    """Run a single strategy on the trace and return metrics."""
    await fsm.setup()

    commands = []
    for pt in trace:
        cmd = await fsm.process(pt.fog_probability)
        if cmd:
            cmd["_timestamp"] = pt.timestamp_s
            commands.append(cmd)

    await fsm.teardown()

    gt_intervals = extract_gt_intervals(trace)
    fsm.mark_false_positives(gt_intervals)

    metrics = fsm.get_metrics()
    events = fsm.cue_events

    fp_count = sum(1 for e in events if e.was_false_positive)
    tp_count = len(events) - fp_count

    detection_lats = compute_detection_latencies(events, gt_intervals)
    detected_gt = len(detection_lats)
    missed_gt = len(gt_intervals) - detected_gt

    metrics.update({
        "strategy": name,
        "true_positives": tp_count,
        "false_positives": fp_count,
        "gt_episodes": len(gt_intervals),
        "detected_episodes": detected_gt,
        "missed_episodes": missed_gt,
        "sensitivity": round(detected_gt / len(gt_intervals), 3)
                       if gt_intervals else 0.0,
        "precision": round(tp_count / len(events), 3) if events else 0.0,
        "fpr": round(fp_count / len(events), 3) if events else 0.0,
    })

    if detection_lats:
        metrics["det_latency_mean_s"] = round(statistics.mean(detection_lats), 3)
        metrics["det_latency_median_s"] = round(statistics.median(detection_lats), 3)
        metrics["det_latency_max_s"] = round(max(detection_lats), 3)
    else:
        metrics["det_latency_mean_s"] = None
        metrics["det_latency_median_s"] = None
        metrics["det_latency_max_s"] = None

    return metrics


async def run_comparison(trace_path: str, output_dir: str | None):
    trace = load_trace(trace_path)
    logger.info("Loaded trace: %d points, %.1fs duration",
                len(trace), trace[-1].timestamp_s - trace[0].timestamp_s)

    gt_intervals = extract_gt_intervals(trace)
    logger.info("Ground truth: %d FoG episodes", len(gt_intervals))

    strategies = {
        "threshold": CueingFSM(
            strategy="threshold",
            threshold_config=ThresholdConfig(
                threshold_high=0.7,
                threshold_low=0.3,
                min_cue_duration_s=1.0,
            ),
        ),
        "fsm": CueingFSM(
            strategy="fsm",
            fsm_config=FSMConfig(
                threshold_high=0.7,
                threshold_low=0.3,
                min_cue_duration_s=1.0,
                cooldown_duration_s=3.0,
                max_cue_duration_s=10.0,
            ),
        ),
        "fsm_aggressive": CueingFSM(
            strategy="fsm",
            fsm_config=FSMConfig(
                threshold_high=0.5,
                threshold_low=0.2,
                min_cue_duration_s=0.5,
                cooldown_duration_s=2.0,
                max_cue_duration_s=8.0,
            ),
        ),
    }

    all_results = []
    for name, fsm in strategies.items():
        logger.info("Running strategy: %s", name)
        metrics = await run_strategy(name, fsm, trace)
        all_results.append(metrics)

    # --- Print comparison table ---
    print("\n" + "=" * 80)
    print("STRATEGY COMPARISON RESULTS")
    print("=" * 80)

    headers = ["Metric", *[r["strategy"] for r in all_results]]
    key_metrics = [
        ("Total cue events", "total_events"),
        ("True positives", "true_positives"),
        ("False positives", "false_positives"),
        ("Sensitivity", "sensitivity"),
        ("Precision", "precision"),
        ("FP rate", "fpr"),
        ("Total cue time (s)", "total_cue_duration_s"),
        ("Mean cue time (s)", "mean_cue_duration_s"),
        ("GT episodes", "gt_episodes"),
        ("Detected", "detected_episodes"),
        ("Missed", "missed_episodes"),
        ("Det latency mean (s)", "det_latency_mean_s"),
        ("Det latency median (s)", "det_latency_median_s"),
        ("Det latency max (s)", "det_latency_max_s"),
    ]

    col_w = 22
    header_line = f"{'Metric':<28s}" + "".join(
        f"{h:>{col_w}s}" for h in [r["strategy"] for r in all_results])
    print(header_line)
    print("-" * len(header_line))

    for label, key in key_metrics:
        values = []
        for r in all_results:
            v = r.get(key, "N/A")
            if v is None:
                values.append("N/A")
            elif isinstance(v, float):
                values.append(f"{v:.3f}")
            else:
                values.append(str(v))
        line = f"{label:<28s}" + "".join(f"{v:>{col_w}s}" for v in values)
        print(line)

    # --- Export ---
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, "strategy_comparison.json")
        with open(out_path, "w") as f:
            json.dump(all_results, f, indent=2)
        logger.info("Results saved to %s", out_path)


def main():
    parser = argparse.ArgumentParser(
        description="Compare threshold vs FSM cueing strategies")
    parser.add_argument("--data", required=True,
                        help="Path to FoG probability trace CSV")
    parser.add_argument("--output", default=None,
                        help="Output directory for results")
    args = parser.parse_args()

    asyncio.run(run_comparison(args.data, args.output))


if __name__ == "__main__":
    main()
