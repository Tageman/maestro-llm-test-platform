import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

from maestro_app.application.flow_translator import (
    OpenAICompatibleFlowTranslator,
    RuleBasedFlowTranslator,
    TranslationError,
)
from maestro_app.application.yaml_compiler import FlowYamlCompiler
from maestro_app.infrastructure.excel_importer import ExcelWorkbookImporter
from m1_helpers import build_sample_workbook


def _snapshot(tmp_path: Path):
    path = build_sample_workbook(tmp_path / "baseline.xlsx")
    return ExcelWorkbookImporter().import_workbook(
        path,
        workbook_id="wb-test",
        source_filename=path.name,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_reset_fixture_maps_to_atomic_clear_state_launch(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    fixture = next(
        item for item in snapshot.fixtures if item.fixture_id == "FX-APP-RESET"
    )

    flow = RuleBasedFlowTranslator().translate_fixture(fixture, snapshot.config)
    commands = flow.model_dump(mode="json")["commands"]

    assert commands[0]["type"] == "launch_app"
    assert commands[0]["clear_state"] is True
    assert commands[1]["type"] == "assert_visible"
    assert commands[1]["selector"]["value"] == "同意并接受"


def test_case_mapping_and_yaml_compilation_are_deterministic(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    flow = RuleBasedFlowTranslator().translate_case(
        snapshot.cases[0], snapshot.config
    )
    compiler = FlowYamlCompiler()

    first = compiler.compile(flow)
    second = compiler.compile(flow)
    documents = list(yaml.safe_load_all(first))

    assert first == second
    assert documents[1] == [
        {"tapOn": "页数"},
        {"tapOn": "尽情发挥"},
        {"tapOn": "确认设置"},
        {"assertVisible": "尽情发挥"},
    ]
    assert flow.commands[-1].source_ref.field.value == "expected_results"


def test_yaml_compiler_escapes_maestro_regex_metacharacters(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    flow = RuleBasedFlowTranslator().translate_case(
        snapshot.cases[0], snapshot.config
    )
    flow.commands[0].selector.value = "确认设置(1)+[A]."

    documents = list(yaml.safe_load_all(FlowYamlCompiler().compile(flow)))

    assert documents[1][0] == {"tapOn": r"确认设置\(1\)\+\[A\]\."}


class _JsonResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def test_openai_adapter_requests_schema_bound_ir(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    expected = RuleBasedFlowTranslator().translate_case(
        snapshot.cases[0], snapshot.config
    )
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.data)
        return _JsonResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": expected.model_dump_json()
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    translator = OpenAICompatibleFlowTranslator(
        base_url="https://llm.example/v1/",
        model="test-model",
        api_key="secret",
        schema={"type": "object"},
        timeout_seconds=7,
    )

    actual = translator.translate_case(snapshot.cases[0], snapshot.config)

    assert actual.flow_id == "TC-HOME-001"
    assert actual.generation_context.model == "test-model"
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["timeout"] == 7
    assert captured["authorization"] == "Bearer secret"
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert captured["payload"]["response_format"]["json_schema"]["strict"] is True
    assert captured["payload"]["temperature"] == 0


def test_openai_adapter_rejects_ir_identity_drift(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    candidate = RuleBasedFlowTranslator().translate_case(
        snapshot.cases[0], snapshot.config
    ).model_copy(update={"flow_id": "INVENTED"})

    def fake_urlopen(request, timeout):
        return _JsonResponse(
            json.dumps(
                {"choices": [{"message": {"content": candidate.model_dump_json()}}]}
            ).encode("utf-8")
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    translator = OpenAICompatibleFlowTranslator(
        base_url="https://llm.example/v1",
        model="test-model",
        api_key=None,
        schema={"type": "object"},
        timeout_seconds=7,
    )

    with pytest.raises(TranslationError, match="flow_id"):
        translator.translate_case(snapshot.cases[0], snapshot.config)


def test_openai_adapter_surfaces_timeout(monkeypatch, tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    def fake_urlopen(request, timeout):
        raise TimeoutError("deadline exceeded")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    translator = OpenAICompatibleFlowTranslator(
        base_url="https://llm.example/v1",
        model="test-model",
        api_key=None,
        schema={"type": "object"},
        timeout_seconds=0.01,
    )

    with pytest.raises(TranslationError, match="LLM 接口调用失败"):
        translator.translate_case(snapshot.cases[0], snapshot.config)
