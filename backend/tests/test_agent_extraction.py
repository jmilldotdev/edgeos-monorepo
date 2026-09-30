"""Grounded extraction rejects untrusted model output and unconsented requests."""

import asyncio
import importlib
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api.agent import extraction
from app.api.agent.schemas import Draft, ExtractDraft

SOURCE = "I want to learn Rust to build safer tools. I can offer Python mentoring."


def suggestions():
    return {
        "intentions": [
            {
                "category": "learn",
                "text": "Learn Rust",
                "why": "To build safer tools",
                "quote": "I want to learn Rust to build safer tools.",
            }
        ],
        "offers": [
            {
                "title": "Python mentoring",
                "detail": "",
                "quote": "I can offer Python mentoring.",
            }
        ],
    }


def test_supported_goals_and_offers_exclude_internal_evidence():
    result = extraction.validate_suggestions(json.dumps(suggestions()), [SOURCE])
    assert result.model_dump() == {
        "intentions": [
            {"category": "learn", "text": "Learn Rust", "why": "To build safer tools"}
        ],
        "offers": [{"title": "Python mentoring", "detail": ""}],
    }


def test_intentions_require_an_explicit_first_person_goal():
    body = suggestions()
    body["intentions"].append(
        {
            "category": "explore",
            "text": "Explore trustworthy agents",
            "why": "",
            "quote": "I’m curious about trustworthy agents.",
        }
    )
    result = extraction.validate_suggestions(
        json.dumps(body), [SOURCE, "I’m curious about trustworthy agents."]
    )
    assert [item.text for item in result.intentions] == ["Learn Rust"]


def test_repeated_suggestions_preserve_first_wording_and_distinct_order():
    body = suggestions()
    body["intentions"].extend([
        {**body["intentions"][0], "text": "  learn   RUST ", "category": "build"},
        {
            "category": "meet",
            "text": "Meet local builders",
            "why": "",
            "quote": "I want to meet local builders.",
        },
    ])
    body["offers"].extend([
        {**body["offers"][0], "title": "PYTHON  mentoring"},
        {
            "title": "Code review",
            "detail": "",
            "quote": "I can help with code review.",
        },
    ])
    result = extraction.validate_suggestions(
        json.dumps(body),
        [SOURCE, "I want to meet local builders. I can help with code review."],
    )
    assert result.model_dump() == {
        "intentions": [
            {"category": "learn", "text": "Learn Rust", "why": "To build safer tools"},
            {"category": "meet", "text": "Meet local builders", "why": ""},
        ],
        "offers": [
            {"title": "Python mentoring", "detail": ""},
            {"title": "Code review", "detail": ""},
        ],
    }


def test_duplicate_cannot_hide_unsupported_evidence():
    body = suggestions()
    body["intentions"].append({
        **body["intentions"][0],
        "quote": "I want to learn Rust for an unstated reason.",
    })
    with pytest.raises(HTTPException) as caught:
        extraction.validate_suggestions(json.dumps(body), [SOURCE])
    assert caught.value.status_code == 502


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body["intentions"][0].update(category="hire"),
        lambda body: body["intentions"][0].update(text=123),
        lambda body: body["intentions"][0].update(text="  "),
        lambda body: body["intentions"][0].update(quote="I want to learn Go"),
        lambda body: body["offers"][0].update(quote=""),
        lambda body: body["offers"][0].update(consent=True),
        lambda body: body.update(intentions=body["intentions"] * 25),
        lambda body: body.update(offers=body["offers"] * 21),
        lambda body: body.pop("offers"),
    ],
)
def test_invalid_or_unsupported_model_output_is_explicit_error(mutation):
    body = suggestions()
    mutation(body)
    with pytest.raises(HTTPException) as caught:
        extraction.validate_suggestions(json.dumps(body), [SOURCE])
    assert caught.value.status_code == 502


def test_evidence_cannot_span_source_boundaries():
    body = suggestions()
    body["intentions"][0]["quote"] = "learn Rust"
    with pytest.raises(HTTPException):
        extraction.validate_suggestions(
            json.dumps(body), ["learn ", "Rust", SOURCE.split(". ")[1]]
        )


def test_no_explicit_goals_or_offers_can_return_empty_arrays():
    result = extraction.validate_suggestions('{"intentions":[],"offers":[]}', ["Hello"])
    assert result.model_dump() == {"intentions": [], "offers": []}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        extraction.settings, "AGENT_EXTRACTION_BASE_URL", "http://127.0.0.1:18434/v1"
    )
    monkeypatch.setattr(extraction.settings, "AGENT_EXTRACTION_MODEL", "test-model")
    monkeypatch.setattr(extraction.settings, "AGENT_EXTRACTION_API_KEY", "private-key")
    client_type = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            extraction.httpx,
            "AsyncClient",
            lambda **kwargs: client_type(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )

    return install


@pytest.mark.parametrize(
    "failure", ["http", "timeout", "malformed", "truncated", "bad-json"]
)
def test_provider_failures_do_not_leak_response_or_secret(provider, failure):
    def handler(request):
        if failure == "http":
            return httpx.Response(401, text="private-key provider diagnostic")
        if failure == "timeout":
            raise httpx.ReadTimeout("private-key", request=request)
        if failure == "bad-json":
            return httpx.Response(200, text="not JSON private-key")
        if failure == "malformed":
            return httpx.Response(200, json={"choices": []})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": json.dumps(suggestions())},
                    }
                ]
            },
        )

    provider(handler)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            extraction.extract_suggestions(Draft(profile={"whatYouDo": SOURCE}))
        )
    assert caught.value.status_code == 502
    assert "private-key" not in caught.value.detail
    assert "diagnostic" not in caught.value.detail


def test_unconfigured_extraction_is_not_fake_success(monkeypatch):
    monkeypatch.setattr(extraction.settings, "AGENT_EXTRACTION_BASE_URL", "")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            extraction.extract_suggestions(Draft(profile={"whatYouDo": SOURCE}))
        )
    assert caught.value.status_code == 503


@pytest.mark.parametrize(
    "consent", [None, {}, {"research": False}, {"research": "true"}, {"training": True}]
)
def test_only_persisted_explicit_research_consent_allows_extraction(
    monkeypatch, consent
):
    routes = importlib.import_module("app.api.agent.router")
    row = None if consent is None else SimpleNamespace(consent=consent)
    db = SimpleNamespace(exec=lambda query: SimpleNamespace(first=lambda: row))
    owner = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())

    async def forbidden_call(_draft):
        pytest.fail("Unconsented source text reached the model")

    monkeypatch.setattr(routes, "extract_suggestions", forbidden_call)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.extract_agent(ExtractDraft(draft=Draft()), db, owner))
    assert caught.value.status_code == 403


def test_combined_context_cap_precedes_provider_call(monkeypatch):
    routes = importlib.import_module("app.api.agent.router")
    db = SimpleNamespace(
        exec=lambda query: SimpleNamespace(
            first=lambda: SimpleNamespace(consent={"research": True})
        )
    )
    owner = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())

    async def forbidden_call(_draft):
        pytest.fail("Oversized context reached the model")

    monkeypatch.setattr(routes, "extract_suggestions", forbidden_call)
    draft = Draft(profile={"whatYouDo": "a" * 11900})
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.extract_agent(ExtractDraft(draft=draft), db, owner))
    assert caught.value.status_code == 400
