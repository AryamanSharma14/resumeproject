"""Strict JSON input and registry-advertised payload schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from walflow.domain.registry import HANDLERS


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    handler: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]
    queue: str = Field(default="default", min_length=1, max_length=64)
    priority: int = Field(default=0, ge=-100, le=100)
    delay_ms: int = Field(default=0, ge=0, le=3_600_000)
    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_ms: int = Field(default=30_000, ge=1, le=600_000)
    depends_on: list[str] | None = Field(default=None)


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=64)
    expression: str = Field(min_length=1, max_length=100)
    handler: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]
    queue: str = Field(default="default", min_length=1, max_length=64)
    priority: int = Field(default=0, ge=-100, le=100)
    timeout_ms: int = Field(default=60_000, ge=1, le=600_000)
    max_attempts: int = Field(default=3, ge=1, le=10)


class RedriveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reset_attempts: bool = Field(default=True)
    updated_payload: dict[str, Any] | None = Field(default=None)


class RedriveBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    queue: str | None = Field(default=None)
    handler: str | None = Field(default=None)
    error_code: str | None = Field(default=None)
    limit: int = Field(default=100, ge=1, le=500)


def handlers() -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {
        "text_summary": {"text": {"type": "string", "maxLength": 100000}},
        "batch_statistics": {
            "numbers": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10000,
                "items": {"type": "number"},
            }
        },
        "demo_flaky": {"fail_times": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1}},
        "demo_delay": {
            "duration_ms": {"type": "integer", "minimum": 0, "maximum": 30000, "default": 0}
        },
    }
    return {
        "items": [
            {
                "name": spec.name,
                "version": spec.version,
                "description": spec.description,
                "payload_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties[name],
                    "required": list(properties[name]),
                },
            }
            for name, spec in HANDLERS.items()
        ]
    }
