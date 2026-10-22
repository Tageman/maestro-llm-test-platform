import base64
import io
import json
import struct
import zlib

import pytest
from PIL import Image

from maestro_app.infrastructure.mcp_client import MaestroMcpError
from maestro_app.infrastructure.mcp_diagnostics import MaestroMcpDiagnosticService as Service


def device(**overrides):
    return {"device_id": "emulator-5554", "connected": True, "platform": "android", "type": "emulator", **overrides}


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return output.getvalue()


def screenshot(data=None):
    return {"content": [{"type": "image", "mimeType": "image/png", "data": base64.b64encode(png_bytes() if data is None else data).decode()}]}


@pytest.mark.parametrize("invalid", [False, True])
def test_real_maestro_jpeg_format_and_truncation(tmp_path, monkeypatch, invalid):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="JPEG")
    raw = buffer.getvalue()
    image = screenshot(raw[:-2] if invalid else raw)
    image["content"][0]["mimeType"] = "image/jpeg"
    client = DiagnosticClient(image=image)
    monkeypatch.setattr("maestro_app.infrastructure.mcp_diagnostics.MaestroMcpClient", lambda *a, **kw: client)
    if invalid:
        with pytest.raises(MaestroMcpError):
            Service().diagnose(maestro_command="unused", device_id="emulator-5554", failed_selector="确认设置", evidence_dir=tmp_path)
        assert not (tmp_path / "screenshot.jpg").exists()
    else:
        result = Service().diagnose(maestro_command="unused", device_id="emulator-5554", failed_selector="确认设置", evidence_dir=tmp_path)
        assert result.screenshot_path.name == "screenshot.jpg"
        assert result.screenshot_path.read_bytes() == raw


class DiagnosticClient:
    """MCP boundary only is replaced; the diagnostic service is real."""
    server_info = {"name": "synthetic-maestro"}

    def __init__(self, devices=None, image=None):
        self.devices = devices if devices is not None else {"content": [{"type": "text", "text": json.dumps({"devices": [device()]})}]}
        self.image = image if image is not None else screenshot()
        self.calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def list_tools(self):
        return {"tools": []}

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return {"list_devices": self.devices, "inspect_screen": {"text": "确认设置(1)"}, "take_screenshot": self.image}[name]


@pytest.mark.parametrize("wrapper", ["direct", "structured", "text", "both"])
def test_exact_online_device_in_supported_containers(wrapper):
    payload = {"devices": [device(), device(device_id="Pixel_5", connected=False)]}
    text = {"type": "text", "text": json.dumps(payload)}
    response = {"direct": payload, "structured": {"structuredContent": payload},
                "text": {"content": [{"type": "text", "text": "informational banner"}, text]},
                "both": {"structuredContent": payload, "content": [text]}}[wrapper]
    Service._require_device(response, "emulator-5554")


@pytest.mark.parametrize("response", [
    {"devices": [device(device_id="emulator-55540")]},
    {"devices": [device(device_id="prefix-emulator-5554")]},
    {"devices": [device(device_id="other", name="emulator-5554")]},
    {"devices": [device(connected=False)]},
    {"devices": [device(connected="true")]},
    {"devices": [device(connected=1)]},
    {"devices": [device(platform="ios")]},
    {"devices": [device(type="physical")]},
    {"devices": [device(), device()]},
    {"devices": [device(), device(connected=False)]},
    {"devices": ["emulator-5554"]},
    {"devices": [{"id": "emulator-5554"}]},
    {"devices": {"device_id": "emulator-5554"}},
    {"devices": []},
    {"message": "emulator-5554"},
    {"content": [{"type": "text", "text": "device_id=emulator-5554"}]},
    {"content": [{"type": "text", "text": '{"devices": broken'}]},
    {"devices": [device()], "structuredContent": {"devices": []}},
    {"devices": [device()], "structuredContent": []},
    {"devices": [device()], "isError": True},
    {"devices": [device()], "content": {}},
])
def test_invalid_or_wrong_device_stops_before_inspection(tmp_path, monkeypatch, response):
    client = DiagnosticClient(devices=response)
    monkeypatch.setattr("maestro_app.infrastructure.mcp_diagnostics.MaestroMcpClient", lambda *a, **kw: client)
    with pytest.raises(MaestroMcpError):
        Service().diagnose(maestro_command="unused", device_id="emulator-5554", failed_selector="确认设置", evidence_dir=tmp_path)
    assert client.calls == [("list_devices", None)]
    assert client.closed and not (tmp_path / "screenshot.png").exists()


@pytest.mark.parametrize("data_url", [False, True])
def test_valid_png_is_preserved_and_both_calls_bind_exact_device(tmp_path, monkeypatch, data_url):
    image = screenshot()
    if data_url:
        image["content"][0]["data"] = "data:image/png;base64," + image["content"][0]["data"]
    client = DiagnosticClient(image=image)
    monkeypatch.setattr("maestro_app.infrastructure.mcp_diagnostics.MaestroMcpClient", lambda *a, **kw: client)
    result = Service().diagnose(maestro_command="unused", device_id="emulator-5554", failed_selector="确认设置", evidence_dir=tmp_path)
    assert result.candidate == "确认设置(1)"
    assert result.screenshot_path.read_bytes() == png_bytes()
    assert all(path.is_file() for path in result.evidence_paths)
    assert client.calls[1:] == [("inspect_screen", {"device_id": "emulator-5554"}), ("take_screenshot", {"device_id": "emulator-5554"})]
    assert client.closed


@pytest.mark.parametrize("mutation", ["text", "empty", "truncated", "crc", "pixels", "bad-base64", "mime", "data-url", "missing", "multiple", "tool-error", "shape", "bytes-limit", "pixels-limit", "dimension-limit"])
def test_invalid_screenshot_never_returns_candidate(tmp_path, monkeypatch, mutation):
    raw = png_bytes()
    image = screenshot()
    if mutation == "text": image = screenshot(b"not an image")
    if mutation == "empty": image = screenshot(b"")
    if mutation == "truncated": image = screenshot(raw[:-12])
    if mutation == "crc": image = screenshot(raw[:29] + bytes([raw[29] ^ 1]) + raw[30:])
    if mutation == "pixels":
        # Correct container CRC, invalid pixel stream: verify() alone is insufficient.
        offset = raw.index(b"IDAT") - 4
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        compressed = zlib.compress(b"")
        chunk = b"IDAT" + compressed
        image = screenshot(raw[:offset] + struct.pack(">I", len(compressed)) + chunk + struct.pack(">I", zlib.crc32(chunk)) + raw[offset + length + 12:])
    if mutation == "bad-base64": image["content"][0]["data"] = "%%%"
    if mutation == "mime": image["content"][0]["mimeType"] = "image/jpeg"
    if mutation == "data-url": image["content"][0]["data"] = "data:image/jpeg;base64," + image["content"][0]["data"]
    if mutation == "missing": image = {"content": []}
    if mutation == "multiple": image["content"] *= 2
    if mutation == "tool-error": image["isError"] = True
    if mutation == "shape": image = {"content": {}}
    if mutation == "bytes-limit": monkeypatch.setattr(Service, "MAX_IMAGE_BYTES", 8)
    if mutation == "pixels-limit": monkeypatch.setattr(Service, "MAX_IMAGE_PIXELS", 32)
    if mutation == "dimension-limit": monkeypatch.setattr(Service, "MAX_IMAGE_DIMENSION", 4)
    client = DiagnosticClient(image=image)
    monkeypatch.setattr("maestro_app.infrastructure.mcp_diagnostics.MaestroMcpClient", lambda *a, **kw: client)
    with pytest.raises(MaestroMcpError):
        Service().diagnose(maestro_command="unused", device_id="emulator-5554", failed_selector="确认设置", evidence_dir=tmp_path)
    assert client.closed and not (tmp_path / "screenshot.png").exists()
