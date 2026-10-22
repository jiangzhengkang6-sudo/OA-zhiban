"""Record synthetic P3 dataset hashes and fresh, network-free test results."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "data/verification/p3"
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, LLM_PROVIDER="mock", OA_PROVIDER="mock", AUTH_PROVIDER="mock")
    reports = []
    for scene in ("work_task", "report", "contract"):
        dataset = root / f"tests/evaluation/p3_{scene}_cases.json"
        data = json.loads(dataset.read_text(encoding="utf-8"))
        splits = {split: [case["id"] for case in data.get("cases", []) if case["split"] == split]
                  if "cases" in data else [case["id"] for case in data[split]]
                  for split in ("development", "acceptance")}
        assert all(len(ids) == 6 for ids in splits.values())
        assert set(splits["development"]).isdisjoint(splits["acceptance"])
        junit = output / f"{scene}-evaluation.xml"
        command = [sys.executable, "-m", "pytest", f"tests/evaluation/test_p3_{scene}_evaluation.py",
                   "-q", f"--junitxml={junit}"]
        result = subprocess.run(command, cwd=root, env=environment, check=False)
        suites = ET.parse(junit).getroot().findall("testsuite")
        counts = {key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        reports.append({"scene": scene, "dataset": str(dataset.relative_to(root)),
                        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                        "case_ids": splits, "provider": "mock", "model": "deterministic/fake",
                        "rule_or_metric_version": "demo-1" if scene == "contract" else 1,
                        "command": command, "exit_code": result.returncode, **counts})
    evidence = {"timestamp": datetime.now(timezone.utc).isoformat(), "kind": "synthetic engineering evaluation",
                "legal_or_production_acceptance": False, "results": reports}
    path = output / "evaluation.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    return int(any(row["exit_code"] or row["failures"] or row["errors"] for row in reports))


if __name__ == "__main__":
    raise SystemExit(main())
