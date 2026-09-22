from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from maestro_app.core.config import Settings
from maestro_app.domain.enums import EntityType, FlowKind, SourceField
from maestro_app.domain.flow_ir import (
    AssertNotVisibleCommand,
    AssertVisibleCommand,
    BackCommand,
    FlowIR,
    GenerationContext,
    InputTextCommand,
    LaunchAppCommand,
    ScrollUntilVisibleCommand,
    SelectorIR,
    SourceRef,
    TapOnCommand,
)
from maestro_app.domain.models import (
    FixtureDefinition,
    ProjectConfig,
    TestCaseDefinition,
)


class TranslationError(ValueError):
    pass


class FlowTranslator(Protocol):
    def translate_case(
        self, case: TestCaseDefinition, config: ProjectConfig
    ) -> FlowIR: ...

    def translate_fixture(
        self, fixture: FixtureDefinition, config: ProjectConfig
    ) -> FlowIR: ...


class RuleBasedFlowTranslator:
    """Deterministic offline translator for the documented Chinese step grammar."""

    prompt_version = "rules-zh-v1"
    model_name = "rule-based-v1"

    def translate_case(
        self, case: TestCaseDefinition, config: ProjectConfig
    ) -> FlowIR:
        commands = self._translate_commands(
            EntityType.CASE,
            case.case_id,
            case.steps,
            case.expected_results,
        )
        return FlowIR(
            schema_version="1.0",
            flow_id=case.case_id,
            flow_kind=FlowKind.CASE,
            app_id=config.app_id,
            name=f"{case.case_id} {case.title}",
            tags=case.tags,
            properties={
                "testCaseId": case.case_id,
                "priority": case.priority,
                "module": case.module,
            },
            commands=commands,
            generation_context=self._context(),
        )

    def translate_fixture(
        self, fixture: FixtureDefinition, config: ProjectConfig
    ) -> FlowIR:
        commands = self._translate_commands(
            EntityType.FIXTURE,
            fixture.fixture_id,
            fixture.steps,
            fixture.expected_results,
        )
        return FlowIR(
            schema_version="1.0",
            flow_id=fixture.fixture_id,
            flow_kind=FlowKind.FIXTURE,
            app_id=config.app_id,
            name=f"{fixture.fixture_id} {fixture.title}",
            tags=["fixture", fixture.phase.value, fixture.scope.value],
            properties={
                "fixtureId": fixture.fixture_id,
                "phase": fixture.phase.value,
                "scope": fixture.scope.value,
            },
            commands=commands,
            generation_context=self._context(),
        )

    def _translate_commands(
        self,
        entity_type: EntityType,
        entity_id: str,
        steps,
        expected_results,
    ) -> list:
        commands: list = []
        for step in steps:
            source = SourceRef(
                entity_type=entity_type,
                entity_id=entity_id,
                field=SourceField.STEPS,
                ordinal=step.ordinal,
                text=step.text,
            )
            text = step.text.strip()
            if re.fullmatch(r"清除\s*APP\s*状态并启动\s*APP", text, re.IGNORECASE):
                commands.append(
                    LaunchAppCommand(
                        type="launch_app",
                        source_ref=source,
                        clear_state=True,
                        stop_app=True,
                    )
                )
                continue
            click = re.search(r"点击【(.+?)】(?:按钮|输入框)?", text)
            if click:
                commands.append(
                    TapOnCommand(
                        type="tap_on",
                        source_ref=source,
                        selector=SelectorIR(strategy="text", value=click.group(1)),
                    )
                )
                continue
            input_match = re.fullmatch(r"输入【(.*?)】", text)
            if input_match:
                commands.append(
                    InputTextCommand(
                        type="input_text",
                        source_ref=source,
                        text=input_match.group(1),
                    )
                )
                continue
            scroll = re.fullmatch(
                r"向(上|下|左|右)滑动直到显示【(.+?)】", text
            )
            if scroll:
                direction = {"上": "up", "下": "down", "左": "left", "右": "right"}[
                    scroll.group(1)
                ]
                commands.append(
                    ScrollUntilVisibleCommand(
                        type="scroll_until_visible",
                        source_ref=source,
                        selector=SelectorIR(strategy="text", value=scroll.group(2)),
                        direction=direction,
                    )
                )
                continue
            if text == "点击系统返回":
                commands.append(BackCommand(type="back", source_ref=source))
                continue
            raise TranslationError(
                f"{entity_id} 操作步骤 {step.ordinal} 不符合一期编写规范：{text}"
            )

        for result in expected_results:
            source = SourceRef(
                entity_type=entity_type,
                entity_id=entity_id,
                field=SourceField.EXPECTED_RESULTS,
                ordinal=result.ordinal,
                text=result.text,
            )
            text = result.text.strip()
            not_visible = re.search(r"页面不显示【(.+?)】", text)
            if not_visible:
                commands.append(
                    AssertNotVisibleCommand(
                        type="assert_not_visible",
                        source_ref=source,
                        selector=SelectorIR(
                            strategy="text", value=not_visible.group(1)
                        ),
                    )
                )
                continue
            visible = re.search(r"页面显示【(.+?)】(?:按钮)?", text)
            if visible:
                commands.append(
                    AssertVisibleCommand(
                        type="assert_visible",
                        source_ref=source,
                        selector=SelectorIR(strategy="text", value=visible.group(1)),
                    )
                )
                continue
            current_value = re.search(r"【.+?】当前值显示为【(.+?)】", text)
            if current_value:
                commands.append(
                    AssertVisibleCommand(
                        type="assert_visible",
                        source_ref=source,
                        selector=SelectorIR(
                            strategy="text", value=current_value.group(1)
                        ),
                    )
                )
                continue
            raise TranslationError(
                f"{entity_id} 预期结果 {result.ordinal} 不能转换为显式断言：{text}"
            )
        return commands

    def _context(self) -> GenerationContext:
        return GenerationContext(
            prompt_version=self.prompt_version,
            model=self.model_name,
            generated_at=datetime.now(UTC),
        )


class OpenAICompatibleFlowTranslator:
    prompt_version = "flow-ir-zh-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        schema: dict[str, Any],
        timeout_seconds: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.schema = schema
        self.timeout_seconds = timeout_seconds

    def translate_case(
        self, case: TestCaseDefinition, config: ProjectConfig
    ) -> FlowIR:
        return self._translate(
            entity=case.model_dump(mode="json"),
            entity_type=EntityType.CASE,
            entity_id=case.case_id,
            app_id=config.app_id,
        )

    def translate_fixture(
        self, fixture: FixtureDefinition, config: ProjectConfig
    ) -> FlowIR:
        return self._translate(
            entity=fixture.model_dump(mode="json"),
            entity_type=EntityType.FIXTURE,
            entity_id=fixture.fixture_id,
            app_id=config.app_id,
        )

    def _translate(
        self,
        *,
        entity: dict[str, Any],
        entity_type: EntityType,
        entity_id: str,
        app_id: str,
    ) -> FlowIR:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 Maestro Flow IR 翻译器。只能返回符合给定 JSON Schema 的 JSON。"
                        "不得返回 YAML、坐标、白名单外命令，不得补造步骤、数据或断言。"
                        "点击文案优先使用 text 选择器；预期结果只能生成断言命令。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "entity_type": entity_type.value,
                            "entity_id": entity_id,
                            "app_id": app_id,
                            "source": entity,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "maestro_flow_ir_v1",
                    "strict": True,
                    "schema": self.schema,
                },
            },
            "temperature": 0,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise TranslationError(f"LLM 接口调用失败：{exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
            candidate = json.loads(content) if isinstance(content, str) else content
            flow = FlowIR.model_validate(candidate)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TranslationError(f"LLM 返回不符合 Flow IR Schema：{exc}") from exc
        if flow.flow_id != entity_id or flow.app_id != app_id:
            raise TranslationError("LLM 返回的 flow_id 或 app_id 与受控输入不一致")
        return flow.model_copy(
            update={
                "generation_context": GenerationContext(
                    prompt_version=self.prompt_version,
                    model=self.model,
                    generated_at=datetime.now(UTC),
                    warnings=flow.generation_context.warnings,
                )
            }
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def build_flow_translator(settings: Settings) -> FlowTranslator:
    if settings.llm_base_url and settings.llm_model:
        schema = json.loads(Path(settings.ir_schema_path).read_text(encoding="utf-8"))
        return OpenAICompatibleFlowTranslator(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            schema=schema,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return RuleBasedFlowTranslator()
