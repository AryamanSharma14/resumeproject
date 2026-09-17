"""Full-stack E2E: live uvicorn API + real spawned worker + packaged static UI.

Verifies the complete local loop end to end: HTTP submit with idempotency,
worker execution through bounded IPC, retry and watchdog-timeout behavior,
cancellation, attempt history, metrics and the served dashboard.

Usage: python scripts/e2e_fullstack.py
Exit 0 = pass; nonzero = failure (prints the failing step).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from relay.api import create_app  # noqa: E402

TOKEN = "e2e-fullstack-token-9876543210"
POLL = 0.25


def await_state(client: httpx.Client, job_id: str, states: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["state"] in states:
            return body
        time.sleep(POLL)
    raise AssertionError(f"job {job_id} did not reach {states}: {body['state']}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="relay-fullstack-") as directory:
        db = str(Path(directory) / "relay.db")
        app = create_app(db, TOKEN)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.monotonic() + 15
        while not server.started:
            assert time.monotonic() < deadline, "API failed to start"
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        worker = subprocess.Popen(
            [str(ROOT / ".venv" / "Scripts" / "relay.exe"), "worker", "start",
             "--db", db, "--queues", "default", "--concurrency", "1"],
            env={**os.environ, "RELAY_TOKEN": TOKEN},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(base_url=base, timeout=10,
                              headers={"Authorization": f"Bearer {TOKEN}"}) as c:
                assert c.get("/health/ready").status_code == 200, "API not ready"
                workers = c.get("/api/v1/workers").json()["items"]
                deadline = time.monotonic() + 20
                while not workers and time.monotonic() < deadline:
                    time.sleep(0.5)
                    workers = c.get("/api/v1/workers").json()["items"]
                assert workers, "worker never registered"
                print("step1 worker registered:", workers[0]["id"])

                r = c.post("/api/v1/jobs", headers={"Idempotency-Key": "fs-1"},
                           json={"handler": "text_summary", "payload": {"text": "full stack relay"}})
                assert r.status_code == 201, r.text
                done = await_state(c, r.json()["job_id"], {"succeeded"}, 30)
                expected = {"characters": 16, "words": 3, "lines": 1}
                assert done["result"] == expected, done["result"]
                print("step2 submit->worker->succeeded:", done["result"])

                r = c.post("/api/v1/jobs", json={"handler": "demo_flaky",
                            "payload": {"fail_times": 1}, "max_attempts": 3})
                flaky = r.json()["job_id"]
                done = await_state(c, flaky, {"succeeded", "failed"}, 60)
                attempts = c.get(f"/api/v1/jobs/{flaky}/attempts").json()["items"]
                assert done["state"] == "succeeded" and len(attempts) == 2, (done, attempts)
                print("step3 retry path: succeeded after", len(attempts), "attempts")

                r = c.post("/api/v1/jobs", json={"handler": "demo_delay",
                            "payload": {"duration_ms": 4000}, "timeout_ms": 800, "max_attempts": 1})
                slow = r.json()["job_id"]
                done = await_state(c, slow, {"failed"}, 60)
                attempts = c.get(f"/api/v1/jobs/{slow}/attempts").json()["items"]
                assert attempts[0]["state"] == "timed_out", attempts[0]
                print("step4 watchdog timeout: failed with timed_out attempt")

                r = c.post("/api/v1/jobs", json={"handler": "demo_delay",
                            "payload": {"duration_ms": 0}, "delay_ms": 60_000})
                cancel_id = r.json()["job_id"]
                assert c.post(f"/api/v1/jobs/{cancel_id}/cancel").status_code == 200
                assert c.get(f"/api/v1/jobs/{cancel_id}").json()["state"] == "canceled"
                print("step5 pending cancel: canceled")

                metrics = c.get("/metrics").text
                assert "relay_jobs{" in metrics and "relay_workers{" in metrics
                print("step6 metrics exposed")

                static_src, static_dst = ROOT / "web" / "dist", ROOT / "src/relay/static"
                if static_dst.exists():
                    shutil.rmtree(static_dst)
                shutil.copytree(static_src, static_dst)
                ui = c.get("/")
                asset = next((static_dst / "assets").glob("index-*.js")).name
                deep = c.get("/jobs")
                assert ui.status_code == 200 and "text/html" in ui.headers["content-type"]
                assert c.get(f"/assets/{asset}").status_code == 200
                assert deep.status_code == 200 and c.get("/no-such-file.js").status_code == 404
                print("step7 dashboard served: / + hashed asset + deep link + 404 for missing asset")
            print("FULLSTACK_E2E_PASS")
            return 0
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
            server.should_exit = True
            time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
