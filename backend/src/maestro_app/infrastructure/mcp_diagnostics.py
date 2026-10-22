from __future__ import annotations

import base64
import json
import io
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

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
    MAX_IMAGE_BYTES = 16 * 1024 * 1024
    MAX_IMAGE_PIXELS = 16_000_000
    MAX_IMAGE_DIMENSION = 8192

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
            self._require_device(devices, device_id)
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
        image_bytes = self._image_bytes(screenshot)
        screenshot_path = evidence_dir / ("screenshot.png" if image_bytes.startswith(b"\x89PNG") else "screenshot.jpg")
        screenshot_path.write_bytes(image_bytes)
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
    def _require_device(result: dict[str, Any], device_id: str) -> None:
        """Parse only documented device-list containers, never arbitrary prose."""
        if not isinstance(result, dict) or result.get("isError"):
            raise MaestroMcpError("Invalid MCP device response")
        payloads = []
        if "devices" in result:
            payloads.append(result)
        if "structuredContent" in result:
            payloads.append(result["structuredContent"])
        content = result.get("content", [])
        if not isinstance(content, list):
            raise MaestroMcpError("Invalid MCP device content")
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            try:
                decoded = json.loads(item.get("text", ""))
            except (ValueError, TypeError):
                continue  # Maestro also emits an informational prose block.
            if isinstance(decoded, dict) and "devices" in decoded:
                payloads.append(decoded)
        lists = []
        for payload in payloads:
            if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
                raise MaestroMcpError("Invalid MCP device list structure")
            devices = payload["devices"]
            ids = []
            for device in devices:
                if not isinstance(device, dict) or not isinstance(device.get("device_id"), str) or not device["device_id"]:
                    raise MaestroMcpError("Invalid MCP device identifier")
                ids.append(device["device_id"])
            if len(ids) != len(set(ids)):
                raise MaestroMcpError("Ambiguous duplicate MCP device identifiers")
            lists.append(devices)
        if not lists or any(devices != lists[0] for devices in lists[1:]):
            raise MaestroMcpError("Missing or conflicting MCP device lists")
        selected = next((device for device in lists[0] if device["device_id"] == device_id), None)
        if (not device_id.startswith("emulator-") or selected is None
                or selected.get("connected") is not True
                or selected.get("platform") != "android"
                or selected.get("type") != "emulator"):
            raise MaestroMcpError(f"MCP did not report the selected connected Android emulator {device_id!r}")

    @classmethod
    def _image_bytes(cls, result: dict[str, Any]) -> bytes:
        if not isinstance(result, dict) or result.get("isError") or not isinstance(result.get("content"), list):
            raise MaestroMcpError("Invalid MCP screenshot response")
        images = [item for item in result["content"] if isinstance(item, dict) and item.get("type") == "image"]
        if len(images) != 1:
            raise MaestroMcpError("MCP screenshot must contain exactly one image")
        item = images[0]
        mime_type = item.get("mimeType")
        image_format = {"image/png": "PNG", "image/jpeg": "JPEG"}.get(mime_type)
        if image_format is None:
            raise MaestroMcpError("MCP screenshot must declare image/png or image/jpeg")
        data = item.get("data") or item.get("image")
        if not isinstance(data, str) or not data:
            raise MaestroMcpError("MCP screenshot contains no image data")
        if data.startswith("data:"):
            if not data.startswith(f"data:{mime_type};base64,"):
                raise MaestroMcpError("MCP screenshot data URL does not match its MIME type")
            data = data.split(",", 1)[1]
        if len(data) > 4 * ((cls.MAX_IMAGE_BYTES + 2) // 3):
            raise MaestroMcpError("MCP screenshot exceeds encoded size limit")
        try:
            decoded = base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise MaestroMcpError("MCP screenshot contains invalid base64") from exc
        complete = (
            decoded.startswith(b"\x89PNG\r\n\x1a\n") and decoded.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
            if image_format == "PNG" else decoded.startswith(b"\xff\xd8\xff") and decoded.endswith(b"\xff\xd9")
        )
        if not decoded or len(decoded) > cls.MAX_IMAGE_BYTES or not complete:
            raise MaestroMcpError("MCP screenshot is not a complete bounded PNG/JPEG")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(decoded), formats=(image_format,)) as image:
                    width, height = image.size
                    if (image.format != image_format or getattr(image, "n_frames", 1) != 1
                            or min(width, height) <= 0
                            or max(width, height) > cls.MAX_IMAGE_DIMENSION
                            or width * height > cls.MAX_IMAGE_PIXELS):
                        raise MaestroMcpError("MCP screenshot has unsupported dimensions or frames")
                    image.verify()  # CRC and container validation.
                with Image.open(io.BytesIO(decoded), formats=(image_format,)) as image:
                    image.load()  # Verify that the actual pixel stream decodes.
        except (OSError, ValueError, SyntaxError, UnidentifiedImageError,
                Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise MaestroMcpError("MCP screenshot image validation failed") from exc
        return decoded
