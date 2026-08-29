"""Named network profiles for deterministic offline and metered tests."""

from edge_delegate.contracts import Connectivity

from .world import SimulatedWorld


def apply_network_profile(world: SimulatedWorld, profile: Connectivity) -> None:
    world.set_connectivity(profile)

