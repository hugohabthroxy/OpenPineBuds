"""
Finite State Machine cueing controller for the HERMES pipeline.

Sits between the AI FoG detection pipeline and the CueingConsumer.
Implements two control strategies:

1. Threshold: simple high/low hysteresis thresholding
2. FSM: IDLE -> CUEING -> COOLDOWN -> IDLE with configurable parameters

Usage within HERMES:
    detector = FoGDetector(...)          # AI Pipeline output
    controller = CueingFSM(strategy="fsm", ...)
    consumer = CueingConsumer(...)
    pipeline.chain(detector, controller, consumer)
"""

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CueState(enum.Enum):
    IDLE = "IDLE"
    CUEING = "CUEING"
    COOLDOWN = "COOLDOWN"


@dataclass
class ThresholdConfig:
    """Simple threshold with hysteresis."""
    threshold_high: float = 0.7
    threshold_low: float = 0.3
    min_cue_duration_s: float = 1.0


@dataclass
class FSMConfig:
    """FSM parameters."""
    threshold_high: float = 0.7
    threshold_low: float = 0.3
    min_cue_duration_s: float = 1.0
    cooldown_duration_s: float = 3.0
    max_cue_duration_s: float = 10.0


@dataclass
class CueEvent:
    """Record of a single cueing event for later analysis."""
    start_time: float = 0.0
    stop_time: float = 0.0
    trigger_probability: float = 0.0
    was_false_positive: bool = False


class CueingFSM:
    """
    HERMES Pipeline component implementing cueing control strategies.

    Receives upstream FoG detection probabilities and emits downstream
    cueing commands (dicts consumed by CueingConsumer.process()).
    """

    def __init__(self,
                 strategy: str = "fsm",
                 threshold_config: Optional[ThresholdConfig] = None,
                 fsm_config: Optional[FSMConfig] = None,
                 tone_id: int = 0,
                 volume: int = 80):
        self.strategy = strategy
        self.threshold_cfg = threshold_config or ThresholdConfig()
        self.fsm_cfg = fsm_config or FSMConfig()
        self.tone_id = tone_id
        self.volume = volume

        self._state = CueState.IDLE
        self._state_enter_time = 0.0
        self._cue_events: list[CueEvent] = []
        self._current_event: Optional[CueEvent] = None
        self._last_probability = 0.0
        self._command_count = 0

    @property
    def state(self) -> CueState:
        return self._state

    @property
    def cue_events(self) -> list[CueEvent]:
        return list(self._cue_events)

    def _enter_state(self, new_state: CueState):
        logger.info("FSM: %s -> %s", self._state.value, new_state.value)
        self._state = new_state
        self._state_enter_time = time.monotonic()

    def _time_in_state(self) -> float:
        return time.monotonic() - self._state_enter_time

    def _start_cue_event(self, probability: float):
        self._current_event = CueEvent(
            start_time=time.time(),
            trigger_probability=probability,
        )

    def _end_cue_event(self):
        if self._current_event:
            self._current_event.stop_time = time.time()
            self._cue_events.append(self._current_event)
            self._current_event = None

    # ---- Control strategy implementations ----

    def _threshold_step(self, probability: float) -> Optional[dict]:
        """Simple threshold with hysteresis."""
        if self._state == CueState.IDLE:
            if probability >= self.threshold_cfg.threshold_high:
                self._enter_state(CueState.CUEING)
                self._start_cue_event(probability)
                return {"action": "start", "tone_id": self.tone_id,
                        "volume": self.volume}
        elif self._state == CueState.CUEING:
            if (probability < self.threshold_cfg.threshold_low and
                    self._time_in_state() >= self.threshold_cfg.min_cue_duration_s):
                self._enter_state(CueState.IDLE)
                self._end_cue_event()
                return {"action": "stop"}
        return None

    def _fsm_step(self, probability: float) -> Optional[dict]:
        """FSM with IDLE -> CUEING -> COOLDOWN -> IDLE."""
        now = time.monotonic()

        if self._state == CueState.IDLE:
            if probability >= self.fsm_cfg.threshold_high:
                self._enter_state(CueState.CUEING)
                self._start_cue_event(probability)
                return {"action": "start", "tone_id": self.tone_id,
                        "volume": self.volume}

        elif self._state == CueState.CUEING:
            time_cueing = self._time_in_state()
            should_stop = (
                (probability < self.fsm_cfg.threshold_low
                 and time_cueing >= self.fsm_cfg.min_cue_duration_s)
                or time_cueing >= self.fsm_cfg.max_cue_duration_s
            )
            if should_stop:
                self._enter_state(CueState.COOLDOWN)
                self._end_cue_event()
                return {"action": "stop"}

        elif self._state == CueState.COOLDOWN:
            if self._time_in_state() >= self.fsm_cfg.cooldown_duration_s:
                self._enter_state(CueState.IDLE)
                logger.info("FSM: cooldown expired, returning to IDLE")

        return None

    # ---- HERMES Pipeline interface ----

    async def setup(self):
        """Called by HERMES on pipeline start."""
        self._state = CueState.IDLE
        self._state_enter_time = time.monotonic()
        logger.info("CueingFSM initialized with strategy='%s'", self.strategy)

    async def process(self, data: Any) -> Optional[dict]:
        """
        Called by HERMES for each upstream data item.

        Expected input: a float (FoG probability 0.0-1.0) or a dict with
        key "fog_probability".

        Returns: a dict command for CueingConsumer, or None if no action.
        """
        if isinstance(data, (int, float)):
            probability = float(data)
        elif isinstance(data, dict):
            probability = float(data.get("fog_probability", 0.0))
        else:
            logger.warning("CueingFSM: unexpected data type %s", type(data))
            return None

        probability = max(0.0, min(1.0, probability))
        self._last_probability = probability

        if self.strategy == "threshold":
            cmd = self._threshold_step(probability)
        else:
            cmd = self._fsm_step(probability)

        if cmd:
            self._command_count += 1
            logger.debug("CueingFSM emitting command #%d: %s",
                         self._command_count, cmd)

        return cmd

    async def teardown(self):
        """Called by HERMES on pipeline stop."""
        if self._state == CueState.CUEING:
            self._end_cue_event()
        logger.info("CueingFSM teardown: %d cue events recorded",
                     len(self._cue_events))

    # ---- Analysis helpers ----

    def get_metrics(self) -> dict:
        """Compute cueing metrics for thesis evaluation."""
        events = self._cue_events
        if not events:
            return {
                "total_events": 0,
                "total_cue_duration_s": 0.0,
                "mean_cue_duration_s": 0.0,
                "commands_issued": self._command_count,
            }

        durations = [e.stop_time - e.start_time for e in events
                     if e.stop_time > e.start_time]
        total_dur = sum(durations)
        mean_dur = total_dur / len(durations) if durations else 0.0

        return {
            "total_events": len(events),
            "total_cue_duration_s": round(total_dur, 3),
            "mean_cue_duration_s": round(mean_dur, 3),
            "max_cue_duration_s": round(max(durations), 3) if durations else 0.0,
            "min_cue_duration_s": round(min(durations), 3) if durations else 0.0,
            "commands_issued": self._command_count,
        }

    def mark_false_positives(self, ground_truth_intervals: list[tuple]):
        """
        Given ground-truth FoG intervals [(start, end), ...], mark events
        that did not overlap with any ground-truth interval as false positives.
        """
        for event in self._cue_events:
            overlap = False
            for gt_start, gt_end in ground_truth_intervals:
                if event.start_time < gt_end and event.stop_time > gt_start:
                    overlap = True
                    break
            event.was_false_positive = not overlap


async def _demo():
    """Demonstrate FSM with simulated probabilities."""
    logging.basicConfig(level=logging.INFO)
    import asyncio

    fsm = CueingFSM(strategy="fsm",
                     fsm_config=FSMConfig(
                         threshold_high=0.6,
                         threshold_low=0.3,
                         min_cue_duration_s=0.5,
                         cooldown_duration_s=2.0,
                     ))
    await fsm.setup()

    probabilities = (
        [0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.8, 0.6]
        + [0.4, 0.2, 0.1, 0.05, 0.02]
        + [0.0] * 5
        + [0.3, 0.5, 0.7, 0.8]
    )

    for i, p in enumerate(probabilities):
        cmd = await fsm.process(p)
        state = fsm.state.value
        print(f"  t={i:3d}  p={p:.2f}  state={state:10s}  cmd={cmd}")
        await asyncio.sleep(0.3)

    await fsm.teardown()
    print("\nMetrics:", fsm.get_metrics())


if __name__ == "__main__":
    import asyncio
    asyncio.run(_demo())
