"""How the multipart request model must be bound, pinned against the published spec.

⚠️ The trap this guards is the one PR #70 shipped and had to fix: the wire keeps working
while `/openapi.json` states something else. Here, omitting `media_type` on `Form(...)`
makes FastAPI advertise `application/x-www-form-urlencoded` for a body that is really
`multipart/form-data`, and every test that posts a file still passes.
"""

from typing import Annotated

import pytest
from fastapi import FastAPI, Form
from fastapi.testclient import TestClient

from ai_engine.service_schemas import BriefFillRequest

FIELDS = {
    "productName": "핸드크림",
    "sellingPoint": "하루 종일 촉촉합니다",
}
FILE = {"productImage": ("a.webp", b"\x52\x49\x46\x46fake", "image/webp")}


def build_app() -> FastAPI:
    """The binding this schema is meant to be used with — copy it into the real router."""
    app = FastAPI()

    @app.post("/v1/brief:fill")
    def create(
        body: Annotated[BriefFillRequest, Form(media_type="multipart/form-data")],
    ) -> dict[str, str]:
        return {"productName": body.product_name, "file": body.product_image.filename or ""}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app())


def test_camel_case_form_fields_bind_to_snake_case_attributes(client: TestClient) -> None:
    response = client.post("/v1/brief:fill", data=FIELDS, files=FILE)
    assert response.status_code == 200
    assert response.json() == {"productName": "핸드크림", "file": "a.webp"}


def test_unknown_form_field_is_rejected(client: TestClient) -> None:
    """`extra="forbid"` reaches form bodies too — a typo must not pass silently."""
    response = client.post("/v1/brief:fill", data={**FIELDS, "prodcutName": "오타"}, files=FILE)
    assert response.status_code == 422


def test_optional_field_may_be_omitted(client: TestClient) -> None:
    """`note` and `artStyle` are absent, not empty — the contract has no `null`."""
    assert client.post("/v1/brief:fill", data=FIELDS, files=FILE).status_code == 200


def test_published_spec_says_multipart(client: TestClient) -> None:
    """⚠️ The regression guard. Drop `media_type` and this flips to urlencoded."""
    spec = client.get("/openapi.json").json()
    content = spec["paths"]["/v1/brief:fill"]["post"]["requestBody"]["content"]
    assert list(content) == ["multipart/form-data"]


def test_published_spec_names_the_contract_fields(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    ref = spec["paths"]["/v1/brief:fill"]["post"]["requestBody"]["content"]["multipart/form-data"][
        "schema"
    ]["$ref"].rsplit("/", 1)[-1]
    properties = spec["components"]["schemas"][ref]["properties"]
    assert set(properties) == {
        "productImage",
        "productName",
        "sellingPoint",
        "note",
    }
