"""Composition for the two-light demonstration; only software state is changed."""

import json
import uuid
from pathlib import Path

from edge_delegate.application import ControlSession, DeviceRegistration, DeviceRegistry
from edge_delegate.planner.control import light_catalog, parse_light_command

from .lights import LightEmulator, light_policy


def open_light_demo(directory):
    """Create/reopen persistent software devices and one authoritative journal."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    entries = tuple(
        DeviceRegistration(
            name,
            LightEmulator(directory / filename),
            light_policy(),
            aliases=("light",),
        )
        for name, filename in (
            ("workbench light", "workbench.sqlite"),
            ("inspection light", "inspection.sqlite"),
        )
    )
    return ControlSession(
        DeviceRegistry(entries),
        catalog=light_catalog(),
        command_parser=parse_light_command,
        journal_path=directory / "gateway.sqlite",
    )


def run_demo(args):
    with open_light_demo(args.directory) as session:
        response = session.command(
            args.text,
            request_id=args.request_id or str(uuid.uuid4()),
            execute=args.execute,
        )
        output = {
            "mode": "execute" if args.execute else "preview",
            "software_only": True,
            "trained_model": False,
            "response": response,
            "state": {
                session.registry.entry(target).name: dict(
                    session.registry.entry(target).device.snapshot().values
                )
                for target in session.registry.targets()
            },
        }
    print(json.dumps(output, indent=2))
    if "gateway" not in response:
        return 2
    gateway = response["gateway"]
    if args.execute:
        return 0 if gateway["result"]["status"] == "executed" else 2
    return 0 if not gateway["validation"]["issues"] else 2
