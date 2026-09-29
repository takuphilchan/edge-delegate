"""Public targeted immediate controls layered over the existing gateway runtime."""

import json
import threading
from contextlib import contextmanager

from edge_delegate.contracts import PlanningRequest
from edge_delegate.contracts._validation import expect_str
from edge_delegate.contracts.control import ControlRequest
from edge_delegate.planner.control import (
    ControlInputError,
    ControlPlanner,
)
from edge_delegate.planner.control_catalog import ControlCatalog

from .devices import DeviceRegistry, TargetResolutionError
from .session import GatewaySession


class _BoundDevice:
    """Recheck immutable registration at every adapter boundary, including dispatch."""

    api_version = "edge-delegate-gateway.v2"

    def __init__(self, registry, target):
        self.registry, self.target = registry, target
        # Auditing a rejected operation must still work after configuration drift.
        self._clock = registry.entry(target).device.clock

    def _device(self):
        return self.registry.entry(self.target).device

    @property
    def device_id(self):
        return self._device().device_id

    @property
    def clock(self):
        return self._clock

    @property
    def capability_cards(self):
        return self._device().capability_cards

    def snapshot(self):
        state = self._device().snapshot()
        self._device()
        return state

    def invoke(self, *_):
        raise RuntimeError("control requires bounded invocation")

    def invoke_bounded(self, *args, **kwargs):
        return self._device().invoke_bounded(*args, **kwargs)

    def reconcile(self, *args, **kwargs):
        return self._device().reconcile(*args, **kwargs)


class ControlSession:
    """Experimental immediate-control SDK, no model or background threads.

    One endpoint per device, one target per request. All devices share one journal,
    so a request ID cannot migrate between them. The session serializes admission;
    durable claims protect devices across sessions/processes sharing that journal.
    No whole-request deadline, dynamic discovery, jobs, or service is claimed.
    """

    def __init__(self, registry: DeviceRegistry, *, catalog, journal_path, command_parser=None):
        if not isinstance(catalog, ControlCatalog):
            raise ValueError("explicit installed ControlCatalog required")
        self.registry = registry
        self.catalog = catalog
        self._command_parser = command_parser
        self._lock = threading.Lock()
        self._state = "initialized"
        self._sessions = {
            target.device_id: GatewaySession(
                ControlPlanner(target, catalog),
                _BoundDevice(registry, target),
                registry.entry(target).policy,
                journal_path=journal_path,
            )
            for target in registry.targets()
        }

    @contextmanager
    def _exclusive(self, *, require_ready=True):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("control session busy")
        try:
            if self._state == "closed":
                raise RuntimeError("control session closed")
            if require_ready and self._state != "ready":
                raise RuntimeError("start the control session before use")
            yield
        finally:
            self._lock.release()

    def start(self):
        with self._exclusive(require_ready=False):
            try:
                for session in self._sessions.values():
                    session.start()
            except Exception:
                self._state = "degraded"
                raise
            self._state = "ready"
        return self

    def close(self):
        if self._state == "closed":
            return
        with self._exclusive(require_ready=False):
            for session in self._sessions.values():
                session.close()
            self._state = "closed"

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    def status(self):
        return {
            "state": self._state,
            "busy": self._lock.locked(),
            "supervised": False,
            "physical_device_qualified": False,
            "targets": [target.to_dict() for target in self.registry.targets()],
        }

    def request(self, *, request_id, target, action, parameters=None):
        """Resolve a name once. Persist this typed request to retry exactly the same work."""
        request = ControlRequest(
            request_id,
            self.registry.resolve(target),
            action,
            {} if parameters is None else parameters,
            self.catalog.fingerprint,
        )
        self.catalog.validate(request.action, request.parameters)
        return request

    def _prepare(self, request):
        if not isinstance(request, ControlRequest):
            raise ValueError(
                "expected ControlRequest; parse wire data with ControlRequest.from_dict"
            )
        request = ControlRequest.from_dict(request.to_dict())
        if request.catalog_sha256 != self.catalog.fingerprint:
            raise ValueError("control catalog changed; do not dispatch")
        self.catalog.validate(request.action, request.parameters)
        self.registry.entry(request.target)
        planning = PlanningRequest.from_dict(
            {
                "request_id": request.request_id,
                "text": json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":")),
            }
        )
        return self._sessions[request.target.device_id], planning

    def preview(self, request):
        with self._exclusive():
            session, planning = self._prepare(request)
            return {
                "schema_version": "edge-control-preview.v1",
                "target": request.target.to_dict(),
                "gateway": session.preview(planning),
            }

    def execute(self, request):
        with self._exclusive():
            session, planning = self._prepare(request)
            return {
                "schema_version": "edge-control-result.v1",
                "target": request.target.to_dict(),
                "gateway": session.execute(planning),
            }

    def reconcile(self, *, target, request_id):
        """Receipt lookup only; supply the original typed target, not a new name lookup."""
        with self._exclusive():
            self.registry.entry(target)
            return self._sessions[target.device_id].reconcile(request_id=request_id)

    def command(self, text, *, request_id, execute=False):
        """Exact command frontend; preview by default. This is not learned inference."""
        expect_str(request_id, "request_id", max_length=128)
        if type(execute) is not bool:
            raise ValueError("execute must be an explicit boolean")
        if self._command_parser is None:
            raise ValueError("no command parser configured; use structured requests")
        try:
            name, action, parameters = self._command_parser(text)
            request = self.request(
                request_id=request_id,
                target=name,
                action=action,
                parameters=parameters,
            )
        except (ControlInputError, TargetResolutionError) as exc:
            with self._exclusive():
                return {
                    "schema_version": "edge-control-response.v1",
                    "status": getattr(exc, "status", "clarification_required"),
                    "request_id": request_id,
                    "message": str(exc),
                    "choices": list(getattr(exc, "choices", ())),
                    "execution_attempted": False,
                }
        return self.execute(request) if execute else self.preview(request)
