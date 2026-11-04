"""The OpenAPI schema documents every error the API can answer with: status, code and message."""

from typing import Any

import pytest

from commitment_tracker.api import app as app_module
from commitment_tracker.api.app import create_app
from commitment_tracker.api.errors import REGISTRY, ErrorCode

HTTP_METHODS = {"get", "post"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return create_app().openapi()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    ]


def test_error_code_is_an_enum_in_the_schema(spec: dict[str, Any]) -> None:
    code = spec["components"]["schemas"]["ErrorBody"]["properties"]["code"]
    values = set(code.get("enum") or spec["components"]["schemas"]["ErrorCode"]["enum"])
    assert values == {c.value for c in ErrorCode}


def test_every_registered_error_uses_a_known_code() -> None:
    assert {e.code for e in REGISTRY} <= set(ErrorCode)
    assert {e.code for e in REGISTRY} == set(ErrorCode)  # no unused code lingers in the enum


def test_every_error_the_app_can_raise_is_documented_on_some_route(spec: dict[str, Any]) -> None:
    documented = {
        (int(status), code)
        for _, _, op in operations(spec)
        for status, response in op["responses"].items()
        if status.isdigit() and int(status) >= 400
        for code in response.get("content", {}).get("application/json", {}).get("examples", {})
    }
    raised = {
        *(e for e in app_module.EXTRACTION_ERRORS.values()),
        *(e for e in app_module.JOB_ERRORS.values()),
        *(e for e in app_module.IMPORT_ERRORS.values()),
    }
    for error in raised:
        assert any(
            status == error.status and key.startswith(error.code) for status, key in documented
        ), f"{error.status} {error.code} is not in the spec"


@pytest.mark.parametrize("error", REGISTRY, ids=lambda e: f"{e.status}-{e.code}")
def test_each_error_has_its_message_in_the_description_and_an_example(
    spec: dict[str, Any], error: Any
) -> None:
    line = f"- `{error.code}`: {error.describe()}"
    found = False
    for _, _, op in operations(spec):
        response = op["responses"].get(str(error.status))
        if response is None or line not in response["description"]:
            continue
        found = True
        examples = response["content"]["application/json"]["examples"]
        assert any(
            e["summary"] == error.describe() and e["value"]["error"]["code"] == error.code
            for e in examples.values()
        )
    assert found, f"{error.code} is on no route"


def test_every_protected_route_documents_the_authorizer_403(spec: dict[str, Any]) -> None:
    for method, path, op in operations(spec):
        has_403 = "403" in op["responses"]
        assert has_403 == (path != "/health"), f"{method} {path}"
    forbidden = spec["paths"]["/analyze"]["post"]["responses"]["403"]
    ref = forbidden["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/GatewayErrorResponse")
    example = forbidden["content"]["application/json"]["examples"]["forbidden"]["value"]
    assert example == {"message": "Forbidden"}


def test_gateway_timeout_is_documented_on_the_long_routes_only(spec: dict[str, Any]) -> None:
    with_504 = {
        f"{method} {path}" for method, path, op in operations(spec) if "504" in op["responses"]
    }
    assert with_504 == {"POST /analyze", "POST /jobs"}
    body = spec["paths"]["/analyze"]["post"]["responses"]["504"]
    assert "29 seconds" in body["description"]
    example = body["content"]["application/json"]["examples"]["gateway_timeout"]["value"]
    assert example == {"message": "Gateway Timeout"}


def test_retry_after_is_documented_where_it_is_sent(spec: dict[str, Any]) -> None:
    analyze = spec["paths"]["/analyze"]["post"]["responses"]
    for status in ("429", "503"):
        header = analyze[status]["headers"]["Retry-After"]
        assert header["schema"]["type"] == "integer"
    assert "headers" not in analyze["502"]
    assert "headers" not in spec["paths"]["/jobs/{job_id}"]["get"]["responses"]["404"]


def test_rate_limit_headers_are_documented_on_limited_successes(spec: dict[str, Any]) -> None:
    for path, method, status in [
        ("/analyze", "post", "200"),
        ("/uploads", "post", "200"),
        ("/jobs", "post", "202"),
        ("/jobs/{job_id}", "get", "200"),
        ("/feedback", "post", "200"),
    ]:
        headers = spec["paths"][path][method]["responses"][status]["headers"]
        assert set(headers) == {"ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"}
    assert "headers" not in spec["paths"]["/samples"]["get"]["responses"]["200"]


def test_validation_error_example_shows_details(spec: dict[str, Any]) -> None:
    examples = spec["paths"]["/analyze"]["post"]["responses"]["422"]["content"]["application/json"][
        "examples"
    ]
    details = examples["validation_error"]["value"]["error"]["details"]
    assert details and set(details[0]) == {"loc", "msg", "type"}
