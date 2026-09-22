from __future__ import annotations

import argparse
import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maestro_app.core.config import get_settings
from maestro_app.infrastructure.mcp_client import MaestroMcpClient, MaestroMcpError


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_first_image(result: dict[str, Any], output_dir: Path) -> Path:
    for block in result.get("content", []):
        if block.get("type") != "image" or not block.get("data"):
            continue
        mime_type = block.get("mimeType", "image/png")
        suffix = ".png" if mime_type == "image/png" else ".jpg"
        path = output_dir / f"device-screenshot{suffix}"
        path.write_bytes(base64.b64decode(block["data"], validate=True))
        return path
    raise MaestroMcpError("take_screenshot did not return an image block")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Maestro MCP lifecycle and collect M0 evidence."
    )
    parser.add_argument("--device-id", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime/m0-mcp-evidence"),
    )
    args = parser.parse_args()

    settings = get_settings()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with MaestroMcpClient(
        settings.maestro_command,
        timeout_seconds=settings.mcp_timeout_seconds,
    ) as client:
        tools = client.list_tools()
        devices = client.call_tool("list_devices")
        hierarchy = client.call_tool(
            "inspect_screen", {"device_id": args.device_id}
        )
        screenshot_result = client.call_tool(
            "take_screenshot", {"device_id": args.device_id}
        )
        screenshot_path = _save_first_image(screenshot_result, output_dir)

        _write_json(output_dir / "server-info.json", client.server_info)
        _write_json(output_dir / "tools.json", tools)
        _write_json(output_dir / "devices.json", devices)
        _write_json(output_dir / "hierarchy.json", hierarchy)
        _write_json(
            output_dir / "summary.json",
            {
                "status": "passed",
                "checked_at": datetime.now(UTC).isoformat(),
                "device_id": args.device_id,
                "screenshot": screenshot_path.name,
            },
        )
    print(f"M0 MCP verification passed: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
