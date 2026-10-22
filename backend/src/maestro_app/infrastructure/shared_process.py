from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

from maestro_app.application.ports import ManagedProcessResult
from maestro_app.infrastructure.owned_process import finish_owned, popen_owned


class SharedPytestProcess:
    def __init__(self, runner, run_id, package):
        self.runner = runner
        self.run_id = run_id
        self.root = package.test_file.parents[2]
        self.package = package
        mapping = json.loads((self.root / "generated/mappings/pytest.json").read_text())
        self.nodes = mapping["node_ids"]
        self.queue = self.root / "shared-worker"
        self.queue.mkdir(exist_ok=False)
        self.sequence = 0
        self.closed = False
        self._abort_lock = threading.Lock()
        self.output = (self.queue / "worker.log").open("wb")
        env = runner._environment(package)
        env["MAESTRO_APP_SHARED_QUEUE"] = str(self.queue)
        try:
            self.process = popen_owned(
                [runner.python_command, "-m", "pytest", "-q", "-s", "-p", "maestro_app.infrastructure.shared_worker", f"--junitxml={self.root / 'reports/shared-suite.xml'}", *self.nodes],
                cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                stdout=self.output, stderr=subprocess.STDOUT, shell=False,
            )
        except BaseException:
            self.output.close()
            raise

    def request(self, package, *, command, timeout_seconds, cancel_event, on_tick=None):
        self.sequence += 1
        node = package.node_ids[0] if package.node_ids else None
        index = self.nodes.index(node) if node else -1
        next_node = self.nodes[index + 1] if 0 <= index < len(self.nodes) - 1 else None
        payload = {
            "command": command, "node_id": node, "next_node_id": next_node,
            "reset_scopes": command == "run" and package.junit_path.parents[1].name != "a1",
            "config_path": str(package.config_path), "junit_path": str(package.junit_path),
            "stdout_path": str(package.stdout_path),
            "runtime": {"attempt_root": str(package.junit_path.parents[1]), "trace_path": str(package.trace_path)},
        }
        path = self.queue / f"{self.sequence:06d}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(path)
        response = self.queue / f"{self.sequence:06d}.done.json"
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        cancelled = False
        while not response.exists():
            if on_tick:
                on_tick()
            if cancel_event.is_set() or time.monotonic() >= deadline:
                cancelled = cancel_event.is_set()
                timed_out = not cancelled
                self.abort()
                break
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        if on_tick:
            on_tick()
        if response.exists():
            code = json.loads(response.read_text())["returncode"]
        else:
            code = 1
            package.stdout_path.parent.mkdir(parents=True, exist_ok=True)
            tail, _ = self.runner._read_tail(self.queue / "worker.log")
            package.stdout_path.write_text("Shared pytest worker interrupted\n" + tail, encoding="utf-8")
        tail, truncated = self.runner._read_tail(package.stdout_path)
        return ManagedProcessResult(code, tail, package.stdout_path, timed_out=timed_out, cancelled=cancelled, output_truncated=truncated)

    def close(self):
        package = replace(
            self.package, node_ids=(),
            junit_path=self.root / "shared-finalization/reports/pytest-junit.xml",
            trace_path=self.root / "shared-finalization/reports/flow-trace.jsonl",
            stdout_path=self.root / "shared-finalization/artifacts/pytest.log",
        )
        if self.closed:
            package.stdout_path.parent.mkdir(parents=True, exist_ok=True)
            message = "共享 pytest 进程已中断，无法确认尚未执行的共享清理；禁止报告清理成功"
            package.stdout_path.write_text(message, encoding="utf-8")
            return package, ManagedProcessResult(1, message, package.stdout_path)
        config = json.loads(package.config_path.read_text())
        budget = (config["timeout_seconds"] + config.get("startup_timeout_seconds", 180)) * max(1, len(config["flow_paths"])) + 30
        try:
            result = self.request(package, command="close", timeout_seconds=budget, cancel_event=threading.Event())
            self.process.wait(timeout=10)
            return package, result
        finally:
            self.abort()

    def abort(self):
        with self._abort_lock:
            if not self.closed:
                self.closed = True
                try:
                    finish_owned(self.process)
                finally:
                    self.output.close()
