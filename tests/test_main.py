import re
import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError, Field
from typing import Optional, Union

from backend.main import (
    replace_placeholders,
    build_dynamic_test_case_model,
    GenerateRequest,
)


class TestBuildDynamicTestCaseModel:
    def test_single_field(self):
        model = build_dynamic_test_case_model(["Название"])
        instance = model(**{"Название": "Test Case"})
        assert instance.field_0 == "Test Case"

    def test_multiple_fields(self):
        fields = ["Название", "Шаги", "Ожидаемый результат"]
        model = build_dynamic_test_case_model(fields)
        instance = model(
            **{
                "Название": "Test",
                "Шаги": "Step 1",
                "Ожидаемый результат": "Result",
            }
        )
        assert instance.field_0 == "Test"
        assert instance.field_1 == "Step 1"
        assert instance.field_2 == "Result"

    def test_list_field_value(self):
        model = build_dynamic_test_case_model(["Шаги"])
        instance = model(**{"Шаги": ["Step 1", "Step 2"]})
        assert instance.field_0 == ["Step 1", "Step 2"]

    def test_extra_fields_ignored(self):
        model = build_dynamic_test_case_model(["Name"])
        instance = model(**{"Name": "Test", "Extra": "Ignored"})
        assert instance.field_0 == "Test"

    def test_field_can_be_none(self):
        model = build_dynamic_test_case_model(["Name"])
        instance = model(**{"Name": None})
        assert instance.field_0 is None

    def test_field_types(self):
        model = build_dynamic_test_case_model(["Field"])
        instance = model(**{"Field": "string"})
        assert isinstance(instance.field_0, str)

    def test_empty_fields_list(self):
        model = build_dynamic_test_case_model([])
        instance = model()
        assert instance.model_dump() == {}


class TestGenerateRequest:
    def test_valid_request(self):
        req = GenerateRequest(task_text="Test task", fields=["Field1", "Field2"])
        assert req.task_text == "Test task"
        assert req.fields == ["Field1", "Field2"]

    def test_empty_fields_list_allowed(self):
        req = GenerateRequest(task_text="Test", fields=[])
        assert req.fields == []

    def test_single_field(self):
        req = GenerateRequest(task_text="Test", fields=["Only"])
        assert req.fields == ["Only"]

    def test_fields_with_special_chars(self):
        req = GenerateRequest(task_text="Test", fields=["Поле №1", "Шаг (важный)"])
        assert req.fields == ["Поле №1", "Шаг (важный)"]

    def test_task_text_with_newlines(self):
        req = GenerateRequest(task_text="Line1\nLine2\nLine3", fields=["A"])
        assert req.task_text == "Line1\nLine2\nLine3"


class TestReplacePlaceholders:
    @patch("backend.main.get_pages_descriptions_batch")
    def test_replaces_single_placeholder(self, mock_batch):
        mock_batch.return_value = [("главная", "описание: кнопка входа, поле email")]
        result = replace_placeholders("Тест {{главная}} страницы")
        assert "--- Описание страницы 'главная' ---" in result
        assert "описание: кнопка входа, поле email" in result
        assert "{{главная}}" not in result
        mock_batch.assert_called_once_with(["главная"])

    @patch("backend.main.get_pages_descriptions_batch")
    def test_multiple_placeholders(self, mock_batch):
        mock_batch.return_value = [("a", "описание A"), ("b", "описание B")]
        result = replace_placeholders("{{A}} и {{B}}")
        assert result.count("--- Описание страницы") == 2
        assert mock_batch.call_count == 1
        assert "описание A" in result
        assert "описание B" in result

    def test_no_placeholder(self):
        result = replace_placeholders("Просто текст без плейсхолдеров")
        assert result == "Просто текст без плейсхолдеров"

    @patch("backend.main.get_pages_descriptions_batch")
    @patch("backend.main.get_all_pages")
    def test_placeholder_not_found_keeps_original(self, mock_get_all, mock_batch):
        mock_batch.return_value = []
        mock_get_all.return_value = [{"name": "другая", "description": "desc"}]
        result = replace_placeholders("Тест {{неизвестная}} страницы")
        assert "{{неизвестная}}" in result
        assert "--- Описание страницы" not in result
        mock_batch.assert_called_once_with(["неизвестная"])
        mock_get_all.assert_called_once()

    @patch("backend.main.get_pages_descriptions_batch")
    def test_empty_description(self, mock_batch):
        mock_batch.return_value = [("пусто", "")]
        result = replace_placeholders("Тест {{пусто}}")
        assert "--- Описание страницы 'пусто' ---" in result
        assert "\n---\n" in result or result.endswith("\n---")
        expected = "\n--- Описание страницы 'пусто' ---\n\n---"
        assert expected in result

    @patch("backend.main.get_pages_descriptions_batch")
    def test_placeholder_at_start(self, mock_batch):
        mock_batch.return_value = [("start", "desc")]
        result = replace_placeholders("{{start}} in text")
        lines = [l for l in result.split("\n") if l.strip()]
        assert any("Описание страницы" in l for l in lines)

    @patch("backend.main.get_pages_descriptions_batch")
    def test_placeholder_at_end(self, mock_batch):
        mock_batch.return_value = [("end", "desc")]
        result = replace_placeholders("text {{end}}")
        assert "Описание страницы 'end'" in result

    @patch("backend.main.get_pages_descriptions_batch")
    def test_multiple_placeholders_same_name(self, mock_batch):
        mock_batch.return_value = [("x", "same desc")]
        result = replace_placeholders("{{x}} и {{x}}")
        assert result.count("Описание страницы 'x'") == 2
        assert mock_batch.call_count == 1

    @patch("backend.main.get_pages_descriptions_batch")
    def test_whitespace_in_placeholder(self, mock_batch):
        mock_batch.return_value = [("spaced", "desc")]
        replace_placeholders("{{  spaced  }}")
        mock_batch.assert_called_once_with(["spaced"])

    @patch("backend.main.get_pages_descriptions_batch")
    def test_description_with_special_chars(self, mock_batch):
        mock_batch.return_value = [("page", 'описание: кнопка "Войти", поле "Email"')]
        result = replace_placeholders("{{page}}")
        assert 'кнопка "Войти"' in result

    @patch("backend.main.get_pages_descriptions_batch")
    def test_unicode_page_name(self, mock_batch):
        mock_batch.return_value = [("русский", "俄语描述")]
        result = replace_placeholders("{{русский}} тест")
        assert "Описание страницы 'русский'" in result
        assert "俄语描述" in result
