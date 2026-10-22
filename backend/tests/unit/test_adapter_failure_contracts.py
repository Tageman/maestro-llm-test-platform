"""Adapter failure matrix: synthetic subprocess/transport, never a real device."""
import sys
import urllib.error

import pytest

from maestro_app.application.syntax_checker import MaestroSyntaxChecker
from maestro_app.infrastructure.device_manager import AndroidDeviceManager, DevicePreparationError
from maestro_app.infrastructure.mcp_client import MaestroMcpClient, MaestroMcpError, StdioJsonRpcTransport
from maestro_app.infrastructure.tool_probe import ProcessResult, SubprocessCommandRunner
from unit.test_device_manager import FakeRunner, _config, _settings
from unit.test_mcp_client import FakeTransport
from unit.test_translation_and_yaml import _JsonResponse, _snapshot
from maestro_app.application.flow_translator import OpenAICompatibleFlowTranslator, TranslationError


@pytest.mark.parametrize("result", [ProcessResult(124, error="timeout"), ProcessResult(127, error="unavailable"), ProcessResult(1, stderr="Malformed command")])
def test_syntax_adapter_never_accepts_timeout_missing_or_invalid_output(tmp_path, result):
    class Runner:
        def run(self, args, timeout_seconds):
            return result
    checked = MaestroSyntaxChecker(Runner()).check(tmp_path / "flow.yaml", maestro_command="maestro", timeout_seconds=1)
    assert not checked.valid and checked.exit_code == result.returncode


@pytest.mark.parametrize("response", [{"id": 1, "result": []}, {"id": 1, "error": {"code": -1, "message": "invalid"}}])
def test_mcp_rejects_invalid_initialization_and_closes_transport(response):
    transport = FakeTransport()
    transport.responses = [response]
    with pytest.raises(MaestroMcpError):
        MaestroMcpClient("unused", transport=transport).start()
    assert transport.closed


@pytest.mark.parametrize("program", ["import time; time.sleep(30)", "print('malformed JSON',flush=True)"])
def test_real_stdio_timeout_or_bad_output_is_bounded_and_closed(program):
    transport = StdioJsonRpcTransport([sys.executable, "-u", "-c", program])
    client = MaestroMcpClient("unused", transport=transport, timeout_seconds=0.2)
    with pytest.raises(MaestroMcpError, match="timed out|closed"):
        client.start()
    assert transport._process is None


def test_real_stdio_unavailable_command_is_not_success(tmp_path):
    transport = StdioJsonRpcTransport([str(tmp_path / "not-a-command")])
    with pytest.raises(MaestroMcpError):
        MaestroMcpClient("unused", transport=transport, timeout_seconds=1).start()
    assert transport._process is None


def test_command_adapter_success_unavailable_timeout(tmp_path):
    runner = SubprocessCommandRunner()
    assert runner.run([sys.executable, "-c", "print('ready')"], 3).succeeded
    assert runner.run([str(tmp_path / "missing")], 3).returncode == 127
    result = runner.run([sys.executable, "-c", "import time;time.sleep(30)"], 0.1)
    assert result.returncode == 124 and "timed out" in result.error


@pytest.mark.parametrize("failure, expected", [
    (ProcessResult(124, error="timeout"), "ADB_DEVICES_FAILED"),
    (ProcessResult(127, error="missing adb"), "ADB_DEVICES_FAILED"),
    (ProcessResult(0, "not a valid device list"), "CONFIGURED_DEVICE_OFFLINE"),
])
def test_device_adapter_failure_and_malformed_response_do_not_start_device(tmp_path, failure, expected):
    class Runner(FakeRunner):
        def run(self, args, timeout_seconds):
            if args[-1] == "devices":
                return failure
            return super().run(args, timeout_seconds)
    manager = AndroidDeviceManager(_settings(tmp_path), Runner(""))
    with pytest.raises(DevicePreparationError) as caught:
        manager.prepare(_config("emulator-5554"))
    assert caught.value.code == expected


@pytest.mark.parametrize("payload", [None, b"not json", b'{"choices": []}', b'{"choices":[{"message":{"content":"{}"}}]}'])
def test_llm_unavailable_or_malformed_response_never_becomes_ir(tmp_path, monkeypatch, payload):
    def response(*args, **kwargs):
        if payload is None:
            raise urllib.error.URLError("service unavailable")
        return _JsonResponse(payload)
    monkeypatch.setattr("urllib.request.urlopen", response)
    snapshot = _snapshot(tmp_path)
    translator = OpenAICompatibleFlowTranslator(base_url="https://unused.invalid/v1", model="synthetic", api_key=None, schema={}, timeout_seconds=1)
    with pytest.raises(TranslationError):
        translator.translate_case(snapshot.cases[0], snapshot.config)
