"""The base every contract v1 wire model shares, and the constrained scalars.

Rules taken from contract/v1/README.md and messages.schema.json:

- ``additionalProperties: false`` everywhere -> ``extra="forbid"``.
- JSON types are exact: strict mode, so ``true`` is never an integer and
  ``"1"`` never a number. ``const`` on a bool or an integer is checked by
  value AND type (``Literal[True]`` would admit ``1``).
- ``pattern`` means the whole string matches: ``re.fullmatch``, so a
  trailing newline never passes a ``$`` anchor.
- Lengths count Unicode code points (Python ``len``).
- Optional fields are omitted, never ``null``: an explicit ``null`` for an
  optional field in JSON input is rejected, and serialization leaves out
  an optional field that is ``None``. A required field typed ``X | None``
  keeps its null.
"""

import re
from typing import Annotated, Final, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    ValidationInfo,
    model_serializer,
    model_validator,
)

# --- Constants ---

CONTRACT_VERSION: Final = 1
MAX_SAFE_INTEGER: Final = 2**53 - 1


# --- Constrained scalars ---


class FullMatch:
    """A validator requiring the whole string to match ``pattern``."""

    def __init__(self, pattern: str) -> None:
        self.pattern = re.compile(pattern)

    def __call__(self, value: str) -> str:
        if self.pattern.fullmatch(value) is None:
            raise ValueError(f"does not match {self.pattern.pattern}")
        return value


def _is_contract_version(value: int) -> int:
    if value != CONTRACT_VERSION:
        raise ValueError(f"v must be {CONTRACT_VERSION}")
    return value


def _is_true(value: bool) -> bool:
    if value is not True:
        raise ValueError("the only allowed value is true")
    return value


Id = Annotated[str, AfterValidator(FullMatch(r"^[A-Za-z0-9._:-]{1,128}$"))]
NodeId = Annotated[str, AfterValidator(FullMatch(r"^[A-Za-z0-9._-]{1,64}$"))]
HostId = Annotated[str, AfterValidator(FullMatch(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"))]
Cursor = Annotated[str, AfterValidator(FullMatch(r"^[!-~]{1,1024}$"))]
EpochMs = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]
Count = Annotated[int, Field(ge=0)]
OpIndex = Annotated[int, Field(ge=0, le=999)]
Url = Annotated[str, Field(min_length=1, max_length=65536)]
Identity = Annotated[str, Field(min_length=1, max_length=65536)]
Title = Annotated[str, Field(max_length=4096)]
Tag = Annotated[str, Field(min_length=1, max_length=64)]
Detail = Annotated[str, Field(max_length=4096)]
ModelId = Annotated[str, Field(min_length=1, max_length=256)]
Version = Annotated[int, AfterValidator(_is_contract_version)]
"""``v`` of every non-frozen message: exactly ``CONTRACT_VERSION``."""
FrozenVersion = Annotated[int, Field(ge=1)]
"""``v`` of ``hello``, ``hello.result`` and ``error``: any version >= 1."""
TrueOnly = Annotated[bool, AfterValidator(_is_true)]


# --- Base model ---


class WireModel(BaseModel):
    """Strict, closed, immutable; optional means omitted, never null."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _optional_is_never_null(cls, data: object, info: ValidationInfo) -> object:
        """On the wire only: Python callers may pass ``None`` for "absent"."""
        if info.mode == "json" and isinstance(data, dict):
            for name, field in cls.model_fields.items():
                key = field.alias or name
                if not field.is_required() and data.get(key, ...) is None:
                    raise ValueError(f"{key}: an optional field is omitted, not null")
        return data

    @model_serializer(mode="wrap")
    def _omit_unset_optionals(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        for name, field in type(self).model_fields.items():
            if not field.is_required() and getattr(self, name) is None:
                data.pop(field.alias or name, None)
                data.pop(name, None)
        return data

    def require_exactly_one(self, *names: str) -> Self:
        """Raise unless exactly one of ``names`` is set (a schema ``oneOf``)."""
        present = [name for name in names if getattr(self, name) is not None]
        if len(present) != 1:
            raise ValueError(f"exactly one of {', '.join(names)} is required")
        return self
