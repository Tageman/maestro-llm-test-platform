from __future__ import annotations

from typing import Any


class ApplicationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: list[dict[str, Any]] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.retryable = retryable


class ResourceNotFound(ApplicationError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            "RESOURCE_NOT_FOUND",
            f"{resource} {resource_id} 不存在",
            status_code=404,
        )


class StateConflict(ApplicationError):
    def __init__(
        self,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            status_code=409,
            details=details,
        )
