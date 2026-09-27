"""Clean wheel/extension acceptance test; runs outside the checkout, without ML.

Usage: python scripts/check_wheel.py --wheel PATH --extension-wheel PATH
Build both wheels with pip wheel --no-deps first. Linux/WSL required.
"""

import argparse
import json
import os
import subprocess
import tempfile
import time
import venv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--extension-wheel", required=True, type=Path)
    args = parser.parse_args()
    wheels = [str(path.resolve(strict=True)) for path in (args.wheel, args.extension_wheel)]
    if os.name != "posix":
        raise SystemExit("Run in Linux/WSL for the Unix adapter acceptance test")
    with tempfile.TemporaryDirectory(prefix="edge-wheel-check-") as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        binaries = root / "venv" / "bin"
        env = {**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1", "HF_HUB_OFFLINE": "1"}

        def run(command, *arguments, expected=0):
            result = subprocess.run(
                [str(binaries / command), *arguments],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != expected:
                raise RuntimeError(
                    f"{command} failed ({result.returncode}): {result.stdout}\n{result.stderr}"
                )
            return result.stdout

        run("python", "-m", "pip", "install", "--no-index", "--no-deps", *wheels)
        run(
            "python",
            "-c",
            "import importlib.util; assert importlib.util.find_spec('torch') is None",
        )
        assert json.loads(run("edge-delegate", "demo"))["display_value"] == 24.5
        run("edge-delegate", "pack-check", "--help")
        run(
            "python",
            "-c",
            "from edge_delegate.model_plugins import available_model_plugins; "
            "from edge_delegate_lab.numeric_challenge import run_challenges; "
            "session = available_model_plugins().get('bounded-commands').create_diagnostic_session("
            "artifact_path=None,settings={'numeric_policy':'decimal.v1'}); "
            "assert session.model_info['trained'] is False; "
            "assert all(c['passed'] for c in run_challenges(session.planner))",
        )
        run(
            "python",
            "-c",
            "from edge_delegate.application import GatewaySession; "
            "from edge_delegate_lab.gateway import GatewaySession as Legacy; "
            "assert GatewaySession is Legacy; "
            "from edge_delegate.data.review_ledger import ReviewLedger; "
            "from edge_delegate_lab.numeric_challenge import challenge_cases; "
            "assert len(challenge_cases()) == 36",
        )
        run("edge-delegate-lab", "init-example", "--output", "profile")
        run("edge-delegate-lab", "profile-check", "--profile", "profile")
        run(
            "edge-delegate-lab",
            "plan",
            "--plugin",
            "display-demo",
            "--profile",
            "profile",
            "--text",
            "Show the temperature.",
        )
        sock = root / "device.sock"
        process = subprocess.Popen(
            [
                str(binaries / "edge-delegate-device"),
                "--socket",
                str(sock),
                "--database",
                str(root / "device.db"),
            ],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 10
            while not sock.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("emulator failed to start")
                time.sleep(0.02)
            command = (
                "run",
                "--plugin",
                "display-demo",
                "--socket",
                str(sock),
                "--journal",
                "journal.db",
                "--policy",
                "profile/policy.json",
                "--text",
                "Show the temperature.",
                "--request-id",
                "smoke",
            )
            result = json.loads(run("edge-delegate-lab", *command))
            assert result["result"]["status"] == "executed"
            replay = json.loads(run("edge-delegate-lab", *command))
            assert all(s["status"] == "replayed" for s in replay["result"]["execution"]["steps"])
        finally:
            process.terminate()
            process.wait(timeout=10)
        (root / "counter-settings.json").write_text(
            json.dumps({"database": str(root / "counter.db")}), encoding="utf-8"
        )
        (root / "counter-policy.json").write_text(
            json.dumps(
                {
                    "schema_version": "policy.v0",
                    "policy_id": "smoke",
                    "granted_permissions": ["counter.write"],
                }
            ),
            encoding="utf-8",
        )
        counter = (
            "run",
            "--plugin",
            "counter-demo",
            "--device-adapter",
            "counter-demo",
            "--device-settings",
            "counter-settings.json",
            "--journal",
            "counter-journal.db",
            "--policy",
            "counter-policy.json",
            "--text",
            "increment counter",
            "--request-id",
            "counter-1",
        )
        first = json.loads(run("edge-delegate-lab", *counter))
        assert first["result"]["execution"]["final_output"] == 1
        retry = json.loads(run("edge-delegate-lab", *counter))
        assert retry["result"]["execution"]["final_output"] == 1
        assert retry["result"]["execution"]["steps"][0]["status"] == "replayed"
        managed = json.loads(
            run(
                "edge-delegate-lab",
                "run",
                "--plugin",
                "display-demo",
                "--emulator-dir",
                str(root / "managed"),
                "--text",
                "Show the temperature.",
                "--format",
                "json",
            )
        )
        assert managed["result"]["status"] == "executed"
        assert not list((root / "managed").glob("*.sock"))
        run("edge-delegate-lab", "generate-data", "--output", "audit-dataset")
        run("edge-delegate-lab", "review-data", "--help")
        # Review workspaces cannot accidentally consume a legacy generated dataset.
        run("edge-delegate-lab", "review-data", "--directory", "audit-dataset", expected=1)
        run(
            "python",
            "-c",
            "from edge_delegate.data.reference_oracle import reference_effects; "
            "result = reference_effects({'task':'display_number','parameters':{'value':12}}, "
            "{'environment.temperature_c':24.5,'display.last_value':None}, "
            "'executed', ['display.value.show']); "
            "assert result['state']['display.last_value'] == 12 and result['exact_state']",
        )
        run(
            "edge-delegate-lab",
            "audit-validation",
            "--plugin",
            "display-demo",
            "--dataset",
            "audit-dataset/validation.jsonl",
            "--output",
            "audit",
        )
        audit = json.loads((root / "audit" / "audit.json").read_text())
        assert audit["complete"] is True and audit["qualified"] is False
    print(
        "PASS: isolated wheel install, profile, preview, Unix execution/replay, managed session, independent counter extension, validation audit, review guard and oracle; no ML dependencies"
    )


if __name__ == "__main__":
    main()
