"""Own a reference emulator child for one CLI session, preserving durable state."""

import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from edge_delegate.adapters.unix import UnixGateway


@contextmanager
def managed_emulator(directory, *, startup_timeout=10):
    if sys.platform != "linux":
        raise ValueError("managed emulator requires Linux/WSL")
    import fcntl

    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("emulator directory must belong to you and have mode 700")
    with (directory / "session.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another managed session owns this emulator directory") from exc
        socket_path = directory / f"session-{uuid.uuid4().hex[:12]}.sock"
        if len(os.fsencode(socket_path)) >= 108:
            raise ValueError("emulator path is too long for a Unix socket; choose a shorter path")
        process = None
        socket_inode = None
        with (directory / "emulator.log").open("ab") as log:
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "edge_delegate.simulator.server",
                        "--socket",
                        str(socket_path),
                        "--database",
                        str(directory / "device.sqlite"),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                deadline = time.monotonic() + startup_timeout
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"emulator exited; inspect {directory / 'emulator.log'}")
                    if socket_path.is_socket():
                        socket_inode = socket_path.stat().st_ino
                        device = UnixGateway(socket_path)
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"emulator startup timed out; inspect {directory / 'emulator.log'}"
                        )
                    time.sleep(0.02)
                yield device, directory / "gateway.sqlite"
            finally:
                if process is not None and process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                # Only remove our own child socket, never databases or a replacement socket.
                if socket_inode is not None and socket_path.is_socket():
                    if socket_path.stat().st_ino == socket_inode:
                        socket_path.unlink()
