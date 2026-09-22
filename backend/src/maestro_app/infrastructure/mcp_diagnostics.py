from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maestro_app.application.locator_repair import HierarchySelectorCandidate
from maestro_app.infrastructure.mcp_client import MaestroMcpClient, MaestroMcpError


@dataclass(frozen=True, slots=True)
class McpDiagnosticResult:
    candidate: str | None
    reason: str
    hierarchy_path: Path
    screenshot_path: Path
    evidence_paths: tuple[Path, ...]


class MaestroMcpDiagnosticService:
    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.candidates = HierarchySelectorCandidate()

    def diagnose(
        self,
        *,
        maestro_command: str,
        device_id: str,
        failed_selector: str,
        evidence_dir: Path,
    ) -> McpDiagnosticResult:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        with MaestroMcpClient(
            maestro_command,
            timeout_seconds=self.timeout_seconds,
        ) as client:
            server_info = client.server_info or {}
            tools = client.list_tools()
            devices = client.call_tool("list_devices")
            if device_id not in json.dumps(devices, ensure_ascii=False):
                raise MaestroMcpError(
                    f"MCP did not report the selected device {device_id!r}"
                )
            hierarchy = client.call_tool(
                "inspect_screen", {"device_id": device_id}
            )
            screenshot = client.call_tool(
                "take_screenshot", {"device_id": device_id}
            )

        server_path = self._json(evidence_dir / "server-info.json", server_info)
        tools_path = self._json(evidence_dir / "tools.json", tools)
        devices_path = self._json(evidence_dir / "devices.json", devices)
        hierarchy_path = self._json(evidence_dir / "hierarchy.json", hierarchy)
        screenshot_response_path = self._json(
            evidence_dir / "screenshot-response.json", screenshot
        )
        screenshot_path = evidence_dir / "screenshot.png"
        screenshot_path.write_bytes(self._image_bytes(screenshot))
        candidate = self.candidates.select(hierarchy, failed_selector)
        reason = (
            f"页面层级中发现唯一相关文本 {candidate!r}"
            if candidate
            else "页面层级中未发现唯一、可证明的相关文本"
        )
        return McpDiagnosticResult(
            candidate=candidate,
            reason=reason,
            hierarchy_path=hierarchy_path,
            screenshot_path=screenshot_path,
            evidence_paths=(
                server_path,
                tools_path,
                devices_path,
                hierarchy_path,
                screenshot_response_path,
                screenshot_path,
            ),
        )

    @staticmethod
    def _json(path: Path, value: Any) -> Path:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _image_bytes(result: dict[str, Any]) -> bytes:
        for item in result.get("content", []):
            if not isinstance(item, dict) or item.get("type") != "image":
                continue
            data = item.get("data") or item.get("image")
            if not isinstance(data, str):
                continue
            if data.startswith("data:") and "," in data:
                data = data.split(",", 1)[1]
            try:
                return base64.b64decode(data, validate=True)
            except ValueError as exc:
                raise MaestroMcpError("MCP screenshot contains invalid base64") from exc
        raise MaestroMcpError("MCP screenshot response did not contain image data")
