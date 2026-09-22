from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maestro_app.domain.enums import (
    EntityType,
    FlowKind,
    SelectorStrategy,
    SourceField,
)


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceRef(IRModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1)
    field: SourceField
    ordinal: int = Field(ge=1)
    text: str = Field(min_length=1)


class SelectorIR(IRModel):
    strategy: SelectorStrategy
    value: str = Field(min_length=1)
    index: int | None = Field(default=None, ge=0)


class CommandBase(IRModel):
    source_ref: SourceRef
    label: str | None = None


class LaunchAppCommand(CommandBase):
    type: Literal["launch_app"]
    clear_state: bool
    stop_app: bool = True


class ClearStateCommand(CommandBase):
    type: Literal["clear_state"]


class TapOnCommand(CommandBase):
    type: Literal["tap_on"]
    selector: SelectorIR


class InputTextCommand(CommandBase):
    type: Literal["input_text"]
    text: str


class EraseTextCommand(CommandBase):
    type: Literal["erase_text"]
    characters: int | None = Field(default=None, ge=1)


class AssertVisibleCommand(CommandBase):
    type: Literal["assert_visible"]
    selector: SelectorIR
    assertion: Literal[True] = True


class AssertNotVisibleCommand(CommandBase):
    type: Literal["assert_not_visible"]
    selector: SelectorIR
    assertion: Literal[True] = True


class ScrollUntilVisibleCommand(CommandBase):
    type: Literal["scroll_until_visible"]
    selector: SelectorIR
    direction: Literal["up", "down", "left", "right"]
    timeout_ms: int | None = Field(default=None, ge=1)


class SwipeCommand(CommandBase):
    type: Literal["swipe"]
    direction: Literal["up", "down", "left", "right"]
    duration_ms: int | None = Field(default=None, ge=1)


class BackCommand(CommandBase):
    type: Literal["back"]


class HideKeyboardCommand(CommandBase):
    type: Literal["hide_keyboard"]


class WaitForAnimationCommand(CommandBase):
    type: Literal["wait_for_animation"]
    timeout_ms: int | None = Field(default=None, ge=1)


class RunFlowCommand(CommandBase):
    type: Literal["run_flow"]
    flow_id: str = Field(min_length=1)
    env: dict[str, str] = Field(default_factory=dict)


class TakeScreenshotCommand(CommandBase):
    type: Literal["take_screenshot"]
    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")


CommandIR = Annotated[
    Union[
        LaunchAppCommand,
        ClearStateCommand,
        TapOnCommand,
        InputTextCommand,
        EraseTextCommand,
        AssertVisibleCommand,
        AssertNotVisibleCommand,
        ScrollUntilVisibleCommand,
        SwipeCommand,
        BackCommand,
        HideKeyboardCommand,
        WaitForAnimationCommand,
        RunFlowCommand,
        TakeScreenshotCommand,
    ],
    Field(discriminator="type"),
]


class GenerationContext(IRModel):
    prompt_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    generated_at: datetime
    warnings: list[str] = Field(default_factory=list)


class FlowIR(IRModel):
    schema_version: Literal["1.0"]
    flow_id: str = Field(min_length=1)
    flow_kind: FlowKind
    app_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)
    commands: list[CommandIR] = Field(min_length=1)
    generation_context: GenerationContext

    @model_validator(mode="after")
    def enforce_source_and_assertion_invariants(self) -> "FlowIR":
        assertion_types = {"assert_visible", "assert_not_visible"}
        for command in self.commands:
            if command.source_ref.entity_id != self.flow_id:
                raise ValueError("command source entity must match flow_id")
            if (
                command.source_ref.field == SourceField.EXPECTED_RESULTS
                and command.type not in assertion_types
            ):
                raise ValueError("expected_results can only produce assertion commands")
        return self
