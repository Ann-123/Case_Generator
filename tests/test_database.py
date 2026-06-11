import os
import pytest
from backend.database import (
    init_db,
    clean_page_name,
    add_or_update_page,
    get_page_description,
    get_all_pages,
    delete_page,
)


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch, tmp_path):
    test_db = tmp_path / "test_pages.db"
    monkeypatch.setattr("backend.database.DB_PATH", str(test_db))
    init_db()
    yield


class TestCleanPageName:
    def test_lowercases_russian(self):
        assert clean_page_name("Главная Страница") == "главная страница"

    def test_strips_whitespace(self):
        assert clean_page_name("  Hello  World  ") == "hello world"

    def test_removes_special_chars(self):
        assert clean_page_name("Special!!!Chars@#$") == "specialchars"

    def test_preserves_hyphen(self):
        assert clean_page_name("with-hyphen") == "with-hyphen"

    def test_handles_empty_string(self):
        assert clean_page_name("") == ""

    def test_all_lowercase(self):
        assert clean_page_name("UPPERCASE") == "uppercase"

    def test_only_special_chars(self):
        assert clean_page_name("!!!") == ""

    def test_unicode_word_chars(self):
        assert clean_page_name("Тест-страница_1") == "тест-страница_1"


class TestAddAndGetPage:
    def test_add_and_retrieve(self):
        add_or_update_page("Test Page", "/path/to/image.png", "Test description")
        desc = get_page_description("Test Page")
        assert desc == "Test description"

    def test_retrieve_nonexistent(self):
        assert get_page_description("Non Existent") is None

    def test_update_existing(self):
        add_or_update_page("Page", "/img1.png", "Desc 1")
        add_or_update_page("Page", "/img2.png", "Desc 2")
        assert get_page_description("Page") == "Desc 2"

    def test_case_insensitive_lookup(self):
        add_or_update_page("CamelCase Name", "/img.png", "Description")
        assert get_page_description("CAMELCASE NAME") == "Description"
        assert get_page_description("camelcase name") == "Description"
        assert get_page_description("CamelCase Name") == "Description"

    def test_retrieve_with_extra_chars_in_query(self):
        add_or_update_page("Clean Name", "/img.png", "Desc")
        assert get_page_description("Clean Name!!!") == "Desc"

    def test_empty_description(self):
        add_or_update_page("Empty Desc", "/img.png", "")
        assert get_page_description("Empty Desc") == ""

    def test_long_description(self):
        long_desc = "A" * 10000
        add_or_update_page("Long", "/img.png", long_desc)
        assert get_page_description("Long") == long_desc


class TestGetAllPages:
    def test_empty_db(self):
        assert get_all_pages() == []

    def test_multiple_pages_ordered(self):
        add_or_update_page("B Page", "/b.png", "Desc B")
        add_or_update_page("A Page", "/a.png", "Desc A")
        pages = get_all_pages()
        assert len(pages) == 2
        assert pages[0]["name"] == "a page"
        assert pages[1]["name"] == "b page"

    def test_returns_name_and_description(self):
        add_or_update_page("MyPage", "/img.png", "My Description")
        pages = get_all_pages()
        assert pages[0] == {"name": "mypage", "description": "My Description"}


class TestDeletePage:
    def test_delete_existing(self):
        add_or_update_page("To Delete", "/img.png", "Desc")
        assert delete_page("To Delete") is True
        assert get_page_description("To Delete") is None

    def test_delete_nonexistent(self):
        assert delete_page("Non Existent") is False

    def test_delete_re_add(self):
        add_or_update_page("Page", "/img.png", "Desc 1")
        delete_page("Page")
        add_or_update_page("Page", "/img2.png", "Desc 2")
        assert get_page_description("Page") == "Desc 2"

    def test_delete_case_insensitive(self):
        add_or_update_page("PageName", "/img.png", "Desc")
        assert delete_page("pagename") is True


class TestConcurrentOperations:
    def test_add_multiple_and_list(self):
        pages_data = [
            ("Login", "login.png", "Login page"),
            ("Dashboard", "dash.png", "Dashboard page"),
            ("Profile", "prof.png", "Profile page"),
        ]
        for name, img, desc in pages_data:
            add_or_update_page(name, img, desc)

        all_pages = get_all_pages()
        assert len(all_pages) == 3
        names = [p["name"] for p in all_pages]
        assert names == ["dashboard", "login", "profile"]

    def test_overwrite_same_page(self):
        for i in range(10):
            add_or_update_page("Page", f"/img_{i}.png", f"Desc_{i}")
        assert get_page_description("Page") == "Desc_9"
