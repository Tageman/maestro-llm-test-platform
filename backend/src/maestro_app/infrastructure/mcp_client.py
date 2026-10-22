from __future__ import annotations

import json
import queue
import subprocess
import threading
from collections import deque
from collections.abc import Mapping
from typing import Any, Protocol, Sequence

from maestro_app.infrastructure.owned_process import finish_owned, popen_owned


class MaestroMcpError(RuntimeError):
    pass


class JsonRpcTransport(Protocol):
    def start(self) -> None: ...

    def send(self, message: Mapping[str, Any]) -> None: ...

    def receive(self, timeout_seconds: float) -> dict[str, Any]: ...

    def close(self) -> None: ...


_EOF = object()


class StdioJsonRpcTransport:
    """Newline-delimited JSON-RPC transport with bounded reads and shutdown."""

    def __init__(self, command: Sequence[str]) -> None:
        self.command = tuple(command)
        self._process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=100)
        self._write_lock = threading.Lock()

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        try:
            self._process = popen_owned(
                list(self.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                shell=False,
                start_new_session=True,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise MaestroMcpError(f"Unable to start Maestro MCP: {exc}") from exc

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def send(self, message: Mapping[str, Any]) -> None:
        process = self._require_running()
        if process.stdin is None:
            raise MaestroMcpError("Maestro MCP stdin is unavailable")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            try:
                process.stdin.write(payload + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise MaestroMcpError(self._closed_message()) from exc

    def receive(self, timeout_seconds: float) -> dict[str, Any]:
        try:
            message = self._messages.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise MaestroMcpError(
                f"Maestro MCP response timed out after {timeout_seconds:g}s"
            ) from exc
        if message is _EOF:
            raise MaestroMcpError(self._closed_message())
        return message

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        finish_owned(process)

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._messages.put(_EOF)
            return
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._stderr.append(f"non-JSON stdout: {line}")
                continue
            if isinstance(message, dict):
                self._messages.put(message)
        self._messages.put(_EOF)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw_line in process.stderr:
            line = raw_line.rstrip()
            if line:
                self._stderr.append(line)

    def _require_running(self) -> subprocess.Popen[str]:
        process = self._process
        if process is None or process.poll() is not None:
            raise MaestroMcpError(self._closed_message())
        return process

    def _closed_message(self) -> str:
        detail = " | ".join(self._stderr)
        return "Maestro MCP process closed" + (f": {detail}" if detail else "")


class MaestroMcpClient:
    protocol_version = "2025-06-18"

    def __init__(
        self,
        maestro_command: str,
        *,
        timeout_seconds: float = 60.0,
        transport: JsonRpcTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.transport = transport or StdioJsonRpcTransport(
            [maestro_command, "mcp"]
        )
        self._next_id = 1
        self._started = False
        self.server_info: dict[str, Any] | None = None

    def __enter__(self) -> "MaestroMcpClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def start(self) -> dict[str, Any]:
        if self._started and self.server_info is not None:
            return self.server_info
        self.transport.start()
        try:
            result = self.request(
                "initialize",
                {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "maestro-llm-test-platform",
                        "version": "0.1.0",
                    },
                },
            )
            self.notify("notifications/initialized")
        except Exception:
            self.transport.close()
            raise
        self.server_info = result
        self._started = True
        return result

    def close(self) -> None:
        self.transport.close()
        self._started = False

    def list_tools(self) -> dict[str, Any]:
        self._require_started()
        return self.request("tools/list", {})

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_started()
        result = self.request(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
        )
        if result.get("isError"):
            raise MaestroMcpError(f"Maestro MCP tool {name!r} returned an error")
        return result

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self.transport.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
        )
        while True:
            response = self.transport.receive(self.timeout_seconds)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise MaestroMcpError(
                    f"Maestro MCP {method!r} failed: {response['error']}"
                )
            result = response.get("result")
            if not isinstance(result, dict):
                raise MaestroMcpError(
                    f"Maestro MCP {method!r} returned an invalid result"
                )
            return result

    def notify(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = dict(params)
        self.transport.send(message)

    def _require_started(self) -> None:
        if not self._started:
            raise MaestroMcpError("Maestro MCP client has not been initialized")
