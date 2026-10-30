import pytest
from fastapi import HTTPException

from app.main import PlanRequest, clean_name, fallback_queries, primary_file


def test_clean_name_removes_unsafe_characters():
    assert clean_name("../My Pack<>") == "..My Pack"


def test_fallback_queries_keeps_description_and_keywords():
    queries = fallback_queries("Хочу магию и драконов в новом мире")
    assert queries[0].startswith("Хочу")
    assert "драконов" in queries


def test_plan_request_validates_description_length():
    assert PlanRequest(description="RPG magic world").description == "RPG magic world"
    with pytest.raises(ValueError):
        PlanRequest(description="abc")


def test_primary_file_prefers_primary_file():
    version = {
        "files": [
            {"filename": "alt.jar", "url": "https://cdn.modrinth.com/data/a.jar", "primary": False},
            {"filename": "main.jar", "url": "https://cdn.modrinth.com/data/b.jar", "primary": True},
        ]
    }
    assert primary_file(version, "demo")["filename"] == "main.jar"


def test_primary_file_rejects_untrusted_host():
    version = {"files": [{"filename": "bad.jar", "url": "https://example.com/bad.jar", "primary": True}]}
    with pytest.raises(HTTPException):
        primary_file(version, "demo")
