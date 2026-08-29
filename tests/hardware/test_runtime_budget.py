"""Explicit hardware check for the configured model-development workstation."""

import pytest


@pytest.mark.hardware
def test_cuda_training_device_is_visible() -> None:
    torch = pytest.importorskip("torch")
    assert torch.cuda.is_available()
    assert torch.cuda.get_device_name(0)
