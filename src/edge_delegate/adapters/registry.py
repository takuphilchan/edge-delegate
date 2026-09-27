"""Explicit selection of installed device adapters; profiles never import code."""

from importlib.metadata import entry_points

from edge_delegate.runtime.ports import DeadlineGateway, DeviceGateway

DEVICE_ADAPTER_GROUP = "edge_delegate.device_adapters.v1"


def unix_adapter(*, settings):
    from .unix import UnixGateway

    if set(settings) - {"socket", "device_id", "timeout_ms"} or "socket" not in settings:
        raise ValueError("unix adapter requires socket; accepts device_id and timeout_ms")
    return UnixGateway(
        settings["socket"],
        **{key: value for key, value in settings.items() if key != "socket"},
    )


def load_device_adapter(adapter_id, *, settings):
    if not isinstance(settings, dict):
        raise ValueError("device settings must be a JSON object")
    # Loading an installed extension runs trusted application code. Only the
    # explicitly selected factory is imported, never a path from a device profile.
    matches = [
        entry for entry in entry_points(group=DEVICE_ADAPTER_GROUP) if entry.name == adapter_id
    ]
    if len(matches) > 1:
        raise ValueError(f"duplicate installed device adapter: {adapter_id}")
    if matches:
        factory = matches[0].load()
    elif adapter_id == "unix":
        factory = unix_adapter
    else:
        raise ValueError(f"device adapter is not installed: {adapter_id}")
    device = factory(settings=settings)
    if (
        not isinstance(device, DeviceGateway)
        or not isinstance(device, DeadlineGateway)
        or device.api_version != "edge-delegate-gateway.v2"
        or not isinstance(device.device_id, str)
        or not device.device_id.strip()
    ):
        raise ValueError("adapter must implement both device and deadline-aware v2 contracts")
    return device
