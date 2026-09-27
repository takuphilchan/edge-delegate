"""Persistent explicit execution session; never used by preview commands."""

import threading
import time
from contextlib import contextmanager
from dataclasses import asdict

from edge_delegate.contracts import PlanIR
from edge_delegate.ir import check_plan
from edge_delegate.planner.base import PlannerContext, PlannerOutputError
from edge_delegate.runtime import Coordinator, Executor
from edge_delegate.runtime.journal import OperationJournal
from edge_delegate.runtime.ports import DeadlineGateway


class GatewaySession:
    """Synchronous session around an already-loaded, caller-owned planner/device.

    No process isolation or whole-request deadline is claimed. Concurrent use is
    rejected, not queued. Close never deletes evidence or closes caller resources.
    """

    def __init__(self, planner, device, policy, *, journal_path, diagnostics=None):
        if (
            not isinstance(device, DeadlineGateway)
            or device.api_version != "edge-delegate-gateway.v2"
        ):
            raise ValueError("execution session requires a deadline-aware gateway")
        if policy.external_allowed:
            raise ValueError("gateway preview is local-only; disable external delegation")
        self.journal = OperationJournal(journal_path)
        self.device = device
        self.diagnostics = diagnostics
        self.planning_ms = 0.0
        self._planner = planner
        self._policy = policy
        self._lock = threading.Lock()
        self._state = "initialized"
        owner = self

        class TimedPlanner:
            def plan(self, request, context):
                recorded = owner.journal.request_plan(device.device_id, request)
                if recorded is not None:
                    return recorded
                started = time.perf_counter()
                try:
                    proposed = planner.plan(request, context)
                finally:
                    owner.planning_ms = (time.perf_counter() - started) * 1000
                if not isinstance(proposed, PlanIR) or proposed.request_id != request.request_id:
                    raise PlannerOutputError("planner must return a plan for this request")
                owner.journal.bind_plan(device.device_id, proposed)
                return proposed

        self.coordinator = Coordinator(
            planner=TimedPlanner(),
            world=device,
            policy=policy,
            executor=Executor(journal=self.journal),
            audit=self.journal,
        )

    @contextmanager
    def _exclusive(self):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("session busy; concurrent work is not admitted")
        try:
            if self._state == "closed":
                raise RuntimeError("session is closed")
            yield
        finally:
            self._lock.release()

    def start(self):
        """Check adapter reachability; model loading/warmup remain caller-owned."""
        with self._exclusive():
            try:
                self.device.snapshot()
            except Exception:
                self._state = "degraded"
                raise
            self._state = "ready"
        return self

    def close(self):
        if self._state == "closed":
            return
        with self._exclusive():
            self._state = "closed"

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    def status(self):
        return {
            "state": self._state,
            "busy": self._lock.locked(),
            "device_id": self.device.device_id,
            "supervised": False,
            "physical_device_qualified": False,
        }

    def preview(self, request):
        """Read context and propose; never reserve a request or dispatch actions."""
        with self._exclusive():
            state = self.device.snapshot()
            context = PlannerContext(
                capabilities=self.device.capability_cards, state=state, policy=self._policy
            )
            plan = self._planner.plan(request, context)
            if not isinstance(plan, PlanIR) or plan.request_id != request.request_id:
                raise PlannerOutputError("planner must return a plan for this request")
            report = check_plan(
                plan, context.capabilities, state, self._policy, now=self.device.clock.now()
            )
            return {
                "schema_version": "edge-gateway-preview.v1",
                "execution_attempted": False,
                "plan": plan.to_dict(),
                "validation": asdict(report),
            }

    def reconcile(self, *, request_id=None, operation_id=None, timeout_ms=500):
        from edge_delegate.runtime.recovery import reconcile_operations

        with self._exclusive():
            return reconcile_operations(
                self.journal,
                self.device,
                request_id=request_id,
                operation_id=operation_id,
                timeout_ms=timeout_ms,
            )

    def execute(self, request):
        with self._exclusive():
            return self._handle(request)

    def handle(self, request):
        """Legacy spelling, preserving edge-gateway-result.v1."""
        return self.execute(request)

    def _handle(self, request):
        started = time.perf_counter()
        self.planning_ms = 0.0
        before = dict(getattr(self.device, "transport_ms", {}))
        journal_before = self.journal.timing_snapshot()
        result = self.coordinator.handle(request)
        total_ms = (time.perf_counter() - started) * 1000
        journal_timing = {
            key: value - journal_before[key]
            for key, value in self.journal.timing_snapshot().items()
        }
        transport = {
            name: value - before.get(name, 0)
            for name, value in getattr(self.device, "transport_ms", {}).items()
        }
        generation = (
            None
            if self.diagnostics is None or not self.planning_ms
            else self.diagnostics.last_generation(include_raw_output=False)
        )
        return {
            "schema_version": "edge-gateway-result.v1",
            "result": asdict(result),
            "total_latency_ms": total_ms,
            "timing": {
                "planning_ms": self.planning_ms,
                "journal": journal_timing,
                "preprocessing_breakdown_ms": None
                if generation is None
                else generation.get("preprocessing_breakdown_ms"),
                "transport_ms": transport,
                "generation_ms": None if generation is None else generation.get("latency_ms"),
                "preprocessing_ms": None
                if generation is None
                else generation.get("preprocessing_ms"),
                "decoding_ms": None if generation is None else generation.get("decoding_ms"),
                "validation_persistence_other_ms": max(
                    0, total_ms - self.planning_ms - sum(transport.values())
                ),
            },
            "generation_resources": None
            if generation is None
            else {
                key: generation.get(key) for key in ("peak_gpu_memory_bytes", "cpu_rss_after_bytes")
            },
            "physical_device_qualified": False,
        }
