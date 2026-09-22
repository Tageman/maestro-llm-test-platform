from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _first_existing_command(configured: str, candidates: list[Path]) -> str:
    if "/" in configured:
        return str(Path(configured).expanduser())

    resolved = shutil.which(configured)
    if resolved:
        return resolved

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return configured


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_name: str = "maestro-llm-test-platform"
    service_version: str = "0.1.0"
    api_version: str = "v1"
    maestro_command: str
    adb_command: str
    emulator_command: str
    app_id: str = Field(min_length=1)
    avd_name: str | None = None
    android_device_id: str | None = None
    runtime_dir: Path
    ir_schema_path: Path
    cors_origins: tuple[str, ...]
    probe_timeout_seconds: float = 30.0
    mcp_timeout_seconds: float = 60.0
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 60.0
    device_boot_timeout_seconds: float = 180.0
    maestro_startup_grace_seconds: float = 180.0
    process_output_limit_chars: int = 200_000

    @classmethod
    def from_environment(cls) -> "Settings":
        project_root = Path(__file__).resolve().parents[4]
        home = Path.home()

        maestro_configured = os.getenv("MAESTRO_COMMAND", "maestro")
        emulator_configured = os.getenv("EMULATOR_COMMAND", "emulator")
        runtime_value = os.getenv("RUNTIME_DIR", str(project_root / "runtime"))
        cors_value = os.getenv(
            "CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        )

        return cls(
            maestro_command=_first_existing_command(
                maestro_configured,
                [home / ".maestro" / "bin" / "maestro"],
            ),
            adb_command=_first_existing_command(os.getenv("ADB_COMMAND", "adb"), []),
            emulator_command=_first_existing_command(
                emulator_configured,
                [home / "Library" / "Android" / "sdk" / "emulator" / "emulator"],
            ),
            app_id=os.getenv("APP_ID", "aippt.com.mm"),
            avd_name=os.getenv("AVD_NAME", "Pixel_5") or None,
            android_device_id=os.getenv("ANDROID_DEVICE_ID") or None,
            runtime_dir=Path(runtime_value).expanduser().resolve(),
            ir_schema_path=project_root / "schemas" / "flow-ir-v1.schema.json",
            cors_origins=tuple(
                origin.strip() for origin in cors_value.split(",") if origin.strip()
            ),
            probe_timeout_seconds=float(
                os.getenv("TOOL_PROBE_TIMEOUT_SECONDS", "30")
            ),
            mcp_timeout_seconds=float(os.getenv("MCP_TIMEOUT_SECONDS", "60")),
            llm_base_url=os.getenv("LLM_BASE_URL") or None,
            llm_model=os.getenv("LLM_MODEL") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            device_boot_timeout_seconds=float(
                os.getenv("DEVICE_BOOT_TIMEOUT_SECONDS", "180")
            ),
            maestro_startup_grace_seconds=float(
                os.getenv("MAESTRO_STARTUP_GRACE_SECONDS", "180")
            ),
            process_output_limit_chars=int(
                os.getenv("PROCESS_OUTPUT_LIMIT_CHARS", "200000")
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()
