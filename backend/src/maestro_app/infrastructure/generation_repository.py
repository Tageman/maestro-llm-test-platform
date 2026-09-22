from __future__ import annotations

import os
import tempfile
from pathlib import Path

from maestro_app.application.errors import ResourceNotFound
from maestro_app.domain.models import GeneratedFlowDetail, GenerationSummary


class GenerationRepository:
    def __init__(self, runtime_dir: Path) -> None:
        self.root = (runtime_dir / "generations").resolve()

    def generation_dir(self, generation_id: str) -> Path:
        self._validate_segment(generation_id)
        path = (self.root / generation_id).resolve()
        if self.root not in path.parents:
            raise ValueError("generation path escapes repository")
        return path

    def flow_dir(self, generation_id: str, flow_id: str) -> Path:
        self._validate_segment(flow_id)
        root = self.generation_dir(generation_id)
        path = (root / "flows" / flow_id).resolve()
        if root not in path.parents:
            raise ValueError("flow path escapes generation")
        return path

    def save_summary(self, summary: GenerationSummary) -> Path:
        root = self.generation_dir(summary.generation_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "generation.json"
        self._write_atomic(
            path, (summary.model_dump_json(indent=2) + "\n").encode("utf-8")
        )
        return path

    def get_summary(self, generation_id: str) -> GenerationSummary:
        path = self.generation_dir(generation_id) / "generation.json"
        if not path.is_file():
            raise ResourceNotFound("generation", generation_id)
        return GenerationSummary.model_validate_json(path.read_text(encoding="utf-8"))

    def write_yaml(self, generation_id: str, flow_id: str, yaml_text: str) -> Path:
        root = self.flow_dir(generation_id, flow_id)
        root.mkdir(parents=True, exist_ok=True)
        initial = root / "initial.yaml"
        final = root / "final.yaml"
        encoded = yaml_text.encode("utf-8")
        self._write_atomic(initial, encoded)
        self._write_atomic(final, encoded)
        return initial

    def write_final_yaml(
        self, generation_id: str, flow_id: str, yaml_text: str
    ) -> Path:
        root = self.flow_dir(generation_id, flow_id)
        root.mkdir(parents=True, exist_ok=True)
        final = root / "final.yaml"
        self._write_atomic(final, yaml_text.encode("utf-8"))
        return final

    def save_flow(
        self, generation_id: str, detail: GeneratedFlowDetail
    ) -> Path:
        root = self.flow_dir(generation_id, detail.flow_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "detail.json"
        self._write_atomic(
            path, (detail.model_dump_json(indent=2) + "\n").encode("utf-8")
        )
        return path

    def get_flow(self, generation_id: str, flow_id: str) -> GeneratedFlowDetail:
        path = self.flow_dir(generation_id, flow_id) / "detail.json"
        if not path.is_file():
            raise ResourceNotFound("flow", flow_id)
        return GeneratedFlowDetail.model_validate_json(path.read_text(encoding="utf-8"))

    def final_yaml_path(self, generation_id: str, flow_id: str) -> Path:
        path = self.flow_dir(generation_id, flow_id) / "final.yaml"
        if not path.is_file():
            raise ResourceNotFound("generated flow", flow_id)
        return path

    @staticmethod
    def _validate_segment(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("identifier must be a safe path segment")

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
