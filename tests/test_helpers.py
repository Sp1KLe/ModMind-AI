from app.main import clean_name, primary_file


def test_clean_name_removes_unsafe_characters():
    assert clean_name("My Pack!?") == "My Pack"


def test_clean_name_has_fallback():
    assert clean_name("!!!") == "ModMind Pack"


def test_primary_file_accepts_modrinth_cdn():
    file_info = primary_file(
        {"files": [{"filename": "example.jar", "url": "https://cdn.modrinth.com/data/example.jar", "primary": True}]},
        "project-id",
    )
    assert file_info["filename"] == "example.jar"
