"""Exercise real HTTP persistence and replay across two owned process restarts.

Uses only the explicitly configured test database, mock providers and port 8014.
Never resets data or stops a process it did not create.
"""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url


def main():
    root = Path(__file__).resolve().parents[1]
    urls = [os.environ.get(name, "") for name in
            ("DATABASE_URL", "DATABASE_SYNC_URL", "CHECKPOINTER_URL")]
    databases = [make_url(url).database for url in urls]
    if os.environ.get("ENVIRONMENT") != "test" or len(set(databases)) != 1 or not databases[0].endswith("_test"):
        raise RuntimeError("Explicit matching test database configuration required")
    port = 8014
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("Verification port 8014 is already in use")
    directory = root / "data/verification/p3"
    directory.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, OA_BACKEND_PORT=str(port), LLM_PROVIDER="mock", OA_PROVIDER="mock",
                       AUTH_PROVIDER="mock", ALLOW_TEST_DATABASE_RESET="false",
                       MOCK_STATE_FILE=str(directory / "restart-mock-state.json"),
                       ATTACHMENT_STORAGE_DIR=str(directory / "restart-attachments"))
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=140)
    process = None
    handles, pids, assertions, replays = [], [], [], []
    suffix = uuid4().hex

    def stop():
        nonlocal process
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            process = None

    def start():
        nonlocal process
        log = (directory / f"restart-process-{len(pids) + 1}.log").open("w", encoding="utf-8")
        handles.append(log)
        process = subprocess.Popen([sys.executable, "run.py"], cwd=root, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        pids.append(process.pid)
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError(f"Backend startup failed; inspect {log.name}")
            try:
                if client.get("/healthz").status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            time.sleep(0.25)
        raise RuntimeError("Backend readiness timed out")

    def call(method, path, payload=None, actor="u_emp_001", replay=False):
        response = client.request(method, "/api" + path, headers={"Authorization": "Bearer mock:" + actor}, json=payload)
        assert response.status_code == 200, (path, response.status_code, response.text)
        result = response.json()["data"]
        if replay:
            replays.append((method, path, deepcopy(payload), actor, deepcopy(result)))
        return result

    def key(name):
        return name + "-" + suffix

    def snapshot(paths):
        return {path: call("GET", path) for path in paths}

    try:
        start()
        meeting = call("POST", "/meetings", {"title": "P3 restart source " + suffix,
                       "content": "Action: Prepare acceptance records.", "idempotency_key": key("meeting")})
        mid = meeting["meeting_id"]
        meeting = call("POST", f"/meetings/{mid}/generate", {"idempotency_key": key("meeting-generate")})
        call("POST", f"/meetings/{mid}/decisions", {"action": "confirm", "expected_version": meeting["version"],
             "idempotency_key": key("meeting-confirm")})
        batch = call("POST", "/work-tasks/batches", {"source_type": "meeting", "source_id": mid,
                     "idempotency_key": key("batch")}, replay=True)
        bid = batch["batch_id"]
        batch = call("POST", f"/work-tasks/batches/{bid}/extract", {"expected_version": batch["version"],
                     "idempotency_key": key("extract")}, replay=True)
        candidate = batch["draft"]["candidates"][0]
        candidate.update(assignee_id="u_emp_001", due_at=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
        batch = call("PATCH", f"/work-tasks/batches/{bid}/draft", {"expected_version": batch["version"],
                     "idempotency_key": key("task-save"), "draft": {"candidates": [candidate]}}, replay=True)
        now = datetime.now(timezone.utc).date()
        report = call("POST", "/reports", {"subject": "P3 restart report " + suffix,
                      "plan": {"metrics": ["ticket_volume", "approval_outcomes", "work_task_progress"],
                               "start": (now - timedelta(days=7)).isoformat(), "end": (now + timedelta(days=1)).isoformat()},
                      "idempotency_key": key("report")}, replay=True)
        rid = report["report_id"]
        report = call("POST", f"/reports/{rid}/approve-plan", {"expected_version": report["version"],
                      "plan_confirmed": True, "idempotency_key": key("approve")}, replay=True)
        contract = call("POST", "/contracts", {"title": "P3 restart contract " + suffix, "reviewer_id": "u_mgr_001",
                        "text": "payment terms: pay within thirty days.\n" * 400,
                        "idempotency_key": key("contract")}, replay=True)
        cid = contract["contract_id"]
        contract = call("POST", f"/contracts/{cid}/commands", {"action": "review", "expected_version": contract["version"],
                        "idempotency_key": key("review")}, replay=True)
        assert contract["draft"]["analysis_engine"] == "deepagents"
        assertions.append("Long contract executed the actual DeepAgents plan and block tools with a mock model")
        paths = [f"/work-tasks/batches/{bid}", f"/work-tasks/batches/{bid}/versions",
                 f"/reports/{rid}", f"/reports/{rid}/versions", f"/contracts/{cid}", f"/contracts/{cid}/versions"]
        before = snapshot(paths)
        stop()
        start()
        assert snapshot(paths) == before
        assertions.append("All three draft records and immutable histories survived the first process restart unchanged")
        batch = call("POST", f"/work-tasks/batches/{bid}/decisions", {"action": "confirm", "expected_version": batch["version"],
                     "selected_candidate_ids": [candidate["candidate_id"]], "metadata_confirmed": True,
                     "risk_acknowledged": True, "idempotency_key": key("task-confirm")}, replay=True)
        tid = batch["task_ids"][0]
        task = call("GET", f"/work-tasks/{tid}")
        for action in ("start", "complete", "archive"):
            task = call("POST", f"/work-tasks/{tid}/commands", {"action": action, "expected_version": task["version"],
                        "idempotency_key": key(action)}, replay=True)
        report = call("POST", f"/reports/{rid}/publish", {"expected_version": report["version"], "definitions_confirmed": True,
                      "causes_acknowledged": True, "idempotency_key": key("publish")}, replay=True)
        contract = call("POST", f"/contracts/{cid}/commands", {"action": "confirm", "expected_version": contract["version"],
                        "dispositions": [{"risk_id": risk["risk_id"], "action": "accepted", "comment": "Reviewed source evidence"}
                                         for risk in contract["draft"]["risks"]], "comment": "Internal mock review completed",
                        "idempotency_key": key("contract-confirm")}, actor="u_mgr_001", replay=True)
        assert (task["status"], report["status"], contract["status"]) == ("ARCHIVED", "PUBLISHED", "CONFIRMED")
        assert all(record["external_writes"] is False for record in (task, report, contract))
        assertions.append("Restored drafts completed through explicit human commands; external_writes remained false")
        paths += [f"/work-tasks/{tid}", f"/work-tasks/{tid}/events"]
        before = snapshot(paths)
        totals = {path: call("GET", path)["total"] for path in ("/work-tasks", "/reports", "/contracts")}
        stop()
        start()
        assert snapshot(paths) == before
        assertions.append("Final task, publication, review decision and histories survived the second process restart unchanged")
        for method, path, payload, actor, original in replays:
            replayed = call(method, path, payload, actor)
            expected = deepcopy(original)
            if path.startswith("/work-tasks/WT-"):
                current = call("GET", path.removesuffix("/commands"), actor=actor)
                for field in ("source", "source_refs", "available_actions"):
                    expected[field] = current[field]
            assert replayed == expected, ("Replay response differs", method, path)
        assert snapshot(paths) == before
        assert totals == {path: call("GET", path)["total"] for path in totals}
        assertions.append(f"All {len(replays)} commands replayed stored business results with current task permissions and no extra records, versions or events")
        assert len(set(pids)) == 3
        digest = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
        evidence = {"timestamp": datetime.now(timezone.utc).isoformat(), "result": "pass", "process_ids": pids,
                    "database": databases[0], "port": port, "providers": "mock", "paid_calls": 0,
                    "external_writes": False, "batch_id": bid, "task_id": tid, "report_id": rid, "contract_id": cid,
                    "snapshot_sha256": digest, "replayed_commands": len(replays), "assertions": assertions}
        path = directory / "restart.json"
        path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        print(path)
    finally:
        stop()
        client.close()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
