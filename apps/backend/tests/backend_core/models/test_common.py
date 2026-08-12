"""The four wire rules, and the enums that carry them.

Every rule here is one the contract states and pydantic does not enforce by itself. The
tests are on a throwaway model rather than a real schema on purpose: the rules belong to
`Base`, so a schema-specific test would only prove that one schema remembered to opt in.
"""

from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

from backend_core.models import Base, Error, ErrorCode, MessageMode, Omittable, OutputType


class Sample(Base):
    """Stand-in with one required field, one optional field and one nested model."""

    product_name: str
    note: Omittable[str] = None


class Wrapper(Base):
    inner: Omittable[Sample] = None


def _wire_names(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def _required_wire_names(model: type[BaseModel]) -> set[str]:
    return {
        field.alias or name for name, field in model.model_fields.items() if field.is_required()
    }


# ---- 규약 1: camelCase on the wire ------------------------------------------------


def test_wire_is_camel_case_while_code_stays_snake_case() -> None:
    parsed = Sample.model_validate({"productName": "핸드크림"})
    assert parsed.product_name == "핸드크림"
    assert parsed.model_dump(by_alias=True) == {"productName": "핸드크림"}


# ---- 규약 3: unknown fields rejected ----------------------------------------------


def test_unknown_field_is_rejected_not_ignored() -> None:
    """A typo must fail loudly — silently dropping it makes both sides believe they agreed."""
    with pytest.raises(ValidationError) as caught:
        Sample.model_validate({"productName": "핸드크림", "prodcutName": "오타"})
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_snake_case_field_name_is_still_accepted() -> None:
    """`populate_by_name` keeps internal construction from having to spell aliases."""
    assert Sample(product_name="핸드크림").product_name == "핸드크림"


# ---- 규약 4: no null, in either direction -----------------------------------------


def test_explicit_null_is_rejected_on_an_optional_field() -> None:
    """`null` is not "absent" — the contract answers 422 rather than guessing which was meant."""
    with pytest.raises(ValidationError):
        Sample.model_validate({"productName": "핸드크림", "note": None})


def test_explicit_null_is_rejected_on_a_required_field() -> None:
    with pytest.raises(ValidationError):
        Sample.model_validate({"productName": None})


def test_absent_field_is_omitted_rather_than_serialized_as_null() -> None:
    assert Sample(product_name="핸드크림").model_dump(by_alias=True) == {"productName": "핸드크림"}


def test_absent_field_is_omitted_in_json_too() -> None:
    """The JSON path is a separate serializer in pydantic; `null` must not leak through it."""
    assert Sample(product_name="핸드크림").model_dump_json(by_alias=True) == (
        '{"productName":"핸드크림"}'
    )


def test_omission_applies_to_nested_models() -> None:
    dumped = Wrapper(inner=Sample(product_name="핸드크림")).model_dump(by_alias=True)
    assert dumped == {"inner": {"productName": "핸드크림"}}


def test_empty_string_is_a_value_and_survives() -> None:
    """An empty string is 비어 있음; an absent key is 없음. Different answers, not two spellings."""
    assert Sample(product_name="핸드크림", note="").model_dump(by_alias=True) == {
        "productName": "핸드크림",
        "note": "",
    }


# ---- 계약 준수: 이 PR 이 들여온 열거형과 Error --------------------------------------


def test_error_code_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    assert set(get_args(ErrorCode)) == set(contract_schemas["ErrorCode"]["enum"])


def test_output_type_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    assert set(get_args(OutputType)) == set(contract_schemas["OutputType"]["enum"])


def test_message_mode_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    assert set(get_args(MessageMode)) == set(contract_schemas["MessageMode"]["enum"])


def test_error_shape_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    schema = contract_schemas["Error"]
    assert _wire_names(Error) == set(schema["properties"])
    assert _required_wire_names(Error) == set(schema["required"])
