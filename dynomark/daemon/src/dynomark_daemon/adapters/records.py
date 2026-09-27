"""Domain values <-> JSON documents, for the SQLite store's rows.

Driven by the dataclasses' own type hints, so a new field needs no codec
change: a dataclass becomes an object tagged with its class name (the tag
picks the member of a union such as ``Operation`` or ``Event``); a tuple or
list becomes an array; a dict becomes an array of ``[key, value]`` pairs
(keys may be values, not strings); an enum becomes its value; a ``NewType``
id is its underlying string. Nothing here knows SQLite.
"""

import dataclasses
import enum
import functools
import json
import types
import typing
from collections.abc import Mapping
from typing import Final

TAG: Final = "$t"

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class RecordError(ValueError):
    """A stored document does not decode into the type asked for."""


# --- Helpers ---


@functools.cache
def _field_hints(cls: type) -> Mapping[str, object]:
    hints = typing.get_type_hints(cls)
    return {field.name: hints[field.name] for field in dataclasses.fields(cls)}


def _is_dataclass_type(hint: object) -> typing.TypeGuard[type]:
    return isinstance(hint, type) and dataclasses.is_dataclass(hint)


def _union_members(hint: object) -> tuple[object, ...] | None:
    origin = typing.get_origin(hint)
    if origin is typing.Union or isinstance(hint, types.UnionType):
        return typing.get_args(hint)
    return None


def encode(value: object) -> JsonValue:
    """The JSON form of a domain value."""
    if value is None or isinstance(value, bool | int | float | str):
        return value.value if isinstance(value, enum.Enum) else value
    if isinstance(value, enum.Enum):
        return encode(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        document: dict[str, JsonValue] = {TAG: type(value).__name__}
        for field in dataclasses.fields(value):
            document[field.name] = encode(getattr(value, field.name))
        return document
    if isinstance(value, tuple | list | frozenset):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return [[encode(key), encode(item)] for key, item in value.items()]
    raise RecordError(f"cannot store a {type(value).__name__}")


def _decode_union(data: JsonValue, members: tuple[object, ...]) -> object:
    if data is None and type(None) in members:
        return None
    candidates = [m for m in members if m is not type(None)]
    if len(candidates) == 1:
        return decode(data, candidates[0])
    tag = data.get(TAG) if isinstance(data, dict) else None
    for member in candidates:
        if _is_dataclass_type(member) and member.__name__ == tag:
            return decode(data, member)
    raise RecordError(f"no member of the union is tagged {tag!r}")


def _decode_dataclass(data: JsonValue, cls: type) -> object:
    if not isinstance(data, dict) or data.get(TAG) != cls.__name__:
        raise RecordError(f"document is not a {cls.__name__}")
    hints = _field_hints(cls)
    missing = set(hints) - set(data)
    if missing:
        raise RecordError(f"{cls.__name__} document lacks {sorted(missing)}")
    return cls(**{name: decode(data[name], hint) for name, hint in hints.items()})


def _decode_collection(data: JsonValue, hint: object, origin: object) -> object:
    if not isinstance(data, list):
        raise RecordError(f"expected an array for {hint}")
    args = typing.get_args(hint)
    if origin is dict:
        key_hint, value_hint = args
        pairs = [item for item in data if isinstance(item, list) and len(item) == 2]
        if len(pairs) != len(data):
            raise RecordError("a dict document holds [key, value] pairs")
        return {decode(k, key_hint): decode(v, value_hint) for k, v in pairs}
    if origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
        if len(args) != len(data):
            raise RecordError(f"expected {len(args)} items for {hint}")
        return tuple(decode(item, arg) for item, arg in zip(data, args, strict=True))
    items = [decode(item, args[0]) for item in data]
    if origin is tuple:
        return tuple(items)
    return frozenset(items) if origin is frozenset else items


def _decode_scalar(data: JsonValue, hint: type) -> object:
    if hint is float and isinstance(data, int | float) and not isinstance(data, bool):
        return float(data)
    if hint is int and (not isinstance(data, int) or isinstance(data, bool)):
        raise RecordError(f"expected an integer, got {data!r}")
    if not isinstance(data, hint):
        raise RecordError(f"expected {hint.__name__}, got {data!r}")
    return data


def decode(data: JsonValue, hint: object) -> object:
    """The domain value of type ``hint`` a JSON form stands for.

    Raises:
        RecordError: the document does not fit ``hint``.
    """
    if isinstance(hint, typing.NewType):
        return decode(data, hint.__supertype__)
    members = _union_members(hint)
    if members is not None:
        return _decode_union(data, members)
    origin = typing.get_origin(hint)
    if origin in (tuple, list, dict, frozenset):
        return _decode_collection(data, hint, origin)
    if _is_dataclass_type(hint):
        return _decode_dataclass(data, hint)
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        try:
            return hint(data)
        except ValueError as error:
            raise RecordError(str(error)) from error
    if hint is type(None):
        if data is not None:
            raise RecordError(f"expected null, got {data!r}")
        return None
    if isinstance(hint, type) and hint in (bool, int, float, str):
        return _decode_scalar(data, hint)
    raise RecordError(f"cannot load a {hint}")


# --- Entry points ---


def dump_record(value: object) -> str:
    """A compact JSON document for ``value``."""
    return json.dumps(encode(value), ensure_ascii=False, separators=(",", ":"))


@typing.overload
def load_record[T](text: str, hint: type[T]) -> T: ...


@typing.overload
def load_record[T](text: str, hint: object, types_: tuple[type[T], ...]) -> T: ...


def load_record[T](text: str, hint: object, types_: tuple[type[T], ...] = ()) -> T:
    """The value of ``hint`` a document holds; for a union alias, ``types_``
    names the classes the result may be (a class ``hint`` needs none).

    Raises:
        RecordError: the document is not a ``hint``.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise RecordError(f"document is not JSON: {error}") from error
    value = decode(data, hint)
    allowed = types_ or ((hint,) if isinstance(hint, type) else ())
    if not allowed or not isinstance(value, allowed):
        raise RecordError(f"document is not a {hint}")
    return typing.cast(T, value)
