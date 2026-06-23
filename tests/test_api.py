import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import tempfile
    import backend.database as db_module

    tmp_db = tempfile.mkstemp(suffix=".db")[1]
    db_module.DB_PATH = tmp_db
    db_module.init_db()

    from backend.main import app

    client = TestClient(app)
    yield client

    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


class TestListPages:
    def test_list_empty(self, client):
        response = client.get("/pages/list")
        assert response.status_code == 200
        assert response.json() == []


class TestUploadPage:
    VISION_RESPONSE_TEXT = (
        "на странице расположены элементы: 'Кнопка входа', 'Поле email'"
    )

    @patch("backend.pages.client.chat.completions.create", new_callable=AsyncMock)
    def test_upload_success(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self.VISION_RESPONSE_TEXT
        mock_create.return_value = mock_response

        response = client.post(
            "/pages/upload",
            files={"file": ("screenshot.png", b"fake-image-data", "image/png")},
            data={"name": "Главная страница"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["name"] == "главная страница"
        assert self.VISION_RESPONSE_TEXT in data["description"]

    @patch("backend.pages.client.chat.completions.create", new_callable=AsyncMock)
    def test_upload_non_image_rejected(self, mock_create, client):
        response = client.post(
            "/pages/upload",
            files={"file": ("test.txt", b"text content", "text/plain")},
            data={"name": "Test"},
        )
        assert response.status_code == 400
        assert "изображением" in response.json()["detail"].lower()
        mock_create.assert_not_called()

    def test_upload_empty_name_rejected(self, client):
        response = client.post(
            "/pages/upload",
            files={"file": ("img.png", b"data", "image/png")},
            data={"name": ""},
        )
        assert response.status_code == 400

    @patch("backend.pages.client.chat.completions.create", new_callable=AsyncMock)
    def test_upload_vision_api_error(self, mock_create, client):
        mock_create.side_effect = Exception("Vision API error")
        response = client.post(
            "/pages/upload",
            files={"file": ("img.png", b"data", "image/png")},
            data={"name": "Test Page"},
        )
        assert response.status_code == 500
        assert "Ошибка распознавания" in response.json()["detail"]

    @patch("backend.pages.client.chat.completions.create", new_callable=AsyncMock)
    def test_upload_and_list(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "desc: button"
        mock_create.return_value = mock_response

        client.post(
            "/pages/upload",
            files={"file": ("img.png", b"data", "image/png")},
            data={"name": "Page1"},
        )

        list_resp = client.get("/pages/list")
        assert list_resp.status_code == 200
        pages = list_resp.json()
        assert any(
            p["name"] == "page1" and p["description"] == "desc: button" for p in pages
        )

    @patch("backend.pages.client.chat.completions.create", new_callable=AsyncMock)
    def test_upload_with_clean_name(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "desc"
        mock_create.return_value = mock_response

        response = client.post(
            "/pages/upload",
            files={"file": ("img.png", b"data", "image/png")},
            data={"name": "  Special!!!Chars  "},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "specialchars"


class TestDeletePage:
    @patch("backend.pages.client.chat.completions.create", new_callable=AsyncMock)
    def test_delete_existing(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "desc"
        mock_create.return_value = mock_response

        client.post(
            "/pages/upload",
            files={"file": ("img.png", b"data", "image/png")},
            data={"name": "ToDelete"},
        )

        response = client.delete("/pages/ToDelete")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        list_resp = client.get("/pages/list")
        pages = list_resp.json()
        assert all(p["name"] != "todelete" for p in pages)

    def test_delete_nonexistent(self, client):
        response = client.delete("/pages/Nonexistent")
        assert response.status_code == 404
        assert "не найдена" in response.json()["detail"]


class TestGenerate:
    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    @patch("backend.main.get_page_description")
    def test_generate_success(self, mock_get_desc, mock_create, client):
        mock_get_desc.return_value = "описание: кнопка входа, поле email"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "test_cases": [
                    {
                        "Название": "Проверка входа",
                        "Шаги": "1. Открыть страницу\n2. Нажать кнопку входа",
                        "Ожидаемый результат": "Пользователь вошёл в систему",
                    }
                ]
            }
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={
                "task_text": "Проверить вход через {{главная}}",
                "fields": ["Название", "Шаги", "Ожидаемый результат"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "test_cases" in data
        assert len(data["test_cases"]) == 1
        tc = data["test_cases"][0]
        assert tc["Название"] == "Проверка входа"
        assert "кнопку входа" in tc["Шаги"]

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    @patch("backend.main.get_page_description")
    def test_generate_with_placeholder_replacement(
        self, mock_get_desc, mock_create, client
    ):
        mock_get_desc.return_value = "описание: кнопка 'Войти'"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "test_cases": [
                    {
                        "Название": "Test",
                        "Шаги": "Нажать кнопку Войти",
                    }
                ]
            }
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={
                "task_text": "Тест {{login_page}}",
                "fields": ["Название", "Шаги"],
            },
        )
        assert response.status_code == 200

        sent_messages = mock_create.call_args[1]["messages"]
        user_msg = [m for m in sent_messages if m["role"] == "user"][0]["content"]
        assert "Описание страницы 'login_page'" in user_msg
        assert "кнопка 'Войти'" in user_msg

    def test_generate_empty_task(self, client):
        response = client.post(
            "/generate",
            json={"task_text": "", "fields": ["Field1"]},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Текст задачи пуст"

    def test_generate_empty_fields(self, client):
        response = client.post(
            "/generate",
            json={"task_text": "Test task", "fields": []},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Список полей шаблона пуст"

    def test_generate_duplicate_fields(self, client):
        response = client.post(
            "/generate",
            json={"task_text": "Test", "fields": ["A", "A"]},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Названия полей должны быть уникальными"

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_model_returns_raw_list(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            [{"Название": "Test", "Шаги": "Step"}]
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={"task_text": "test", "fields": ["Название", "Шаги"]},
        )
        assert response.status_code == 200
        assert len(response.json()["test_cases"]) == 1

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_list_field_conversion(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {"test_cases": [{"Название": "Test", "Шаги": ["Step 1", "Step 2"]}]}
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={"task_text": "test", "fields": ["Название", "Шаги"]},
        )
        assert response.status_code == 200
        tc = response.json()["test_cases"][0]
        assert "Step 1\nStep 2" == tc["Шаги"]

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_model_returns_invalid_json(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not valid json"
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={"task_text": "test", "fields": ["Название"]},
        )
        assert response.status_code == 500
        assert "JSON" in response.json()["error"]

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_no_test_cases_key(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({"wrong_key": []})
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={"task_text": "test", "fields": ["Название"]},
        )
        assert response.status_code == 422
        assert response.json()["error"] == "Ни один тест-кейс не прошёл валидацию"

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_case_with_unknown_fields(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {"test_cases": [{"WrongField": "value"}]}
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={"task_text": "test", "fields": ["Название"]},
        )
        assert response.status_code == 200
        tc = response.json()["test_cases"][0]
        assert tc["Название"] is None

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_llm_exception(self, mock_create, client):
        mock_create.side_effect = RuntimeError("LLM service unavailable")

        response = client.post(
            "/generate",
            json={"task_text": "test", "fields": ["Название"]},
        )
        assert response.status_code == 500
        assert "Ошибка:" in response.json()["error"]


class TestGenerateChecklist:
    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_checklist_success(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "checklist": {
                    "positive": [
                        {
                            "area": "Авторизация",
                            "items": [
                                {"id": "p-1", "text": "Проверить вход с валидным email и паролем"}
                            ],
                        }
                    ],
                    "negative": [
                        {
                            "area": "Авторизация",
                            "items": [
                                {"id": "n-1", "text": "Проверить вход с неверным паролем"}
                            ],
                        }
                    ],
                    "affected_areas": ["Авторизация"],
                }
            }
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate-checklist",
            json={"task_text": "Проверить форму входа"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "checklist" in data
        checklist = data["checklist"]
        assert "positive" in checklist
        assert "negative" in checklist
        assert isinstance(checklist["positive"], list)
        assert len(checklist["positive"]) == 1
        assert checklist["positive"][0]["items"][0]["id"] == "p-1"
        assert "affected_areas" in checklist
        assert "Авторизация" in checklist["affected_areas"]

    def test_generate_checklist_empty_task(self, client):
        response = client.post(
            "/generate-checklist",
            json={"task_text": ""},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Текст задачи пуст"

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_checklist_invalid_json(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not valid json"
        mock_create.return_value = mock_response

        response = client.post(
            "/generate-checklist",
            json={"task_text": "test"},
        )
        assert response.status_code == 500
        assert "JSON" in response.json()["error"]

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_checklist_no_structure(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({"wrong": "data"})
        mock_create.return_value = mock_response

        response = client.post(
            "/generate-checklist",
            json={"task_text": "test"},
        )
        assert response.status_code == 500
        assert "чек-листа" in response.json()["error"]

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_checklist_llm_exception(self, mock_create, client):
        mock_create.side_effect = RuntimeError("LLM error")

        response = client.post(
            "/generate-checklist",
            json={"task_text": "test"},
        )
        assert response.status_code == 500

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_checklist_missing_sections(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {"checklist": {"positive": [{"area": "Логин", "items": [{"id": "p-1", "text": "Test"}]}]}}
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate-checklist",
            json={"task_text": "test"},
        )
        assert response.status_code == 200
        checklist = response.json()["checklist"]
        assert "negative" in checklist
        assert checklist["negative"] == []
        assert "affected_areas" in checklist
        assert checklist["affected_areas"] == []


class TestGenerateWithChecklist:
    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    @patch("backend.main.get_page_description")
    def test_generate_with_checklist_items(self, mock_get_desc, mock_create, client):
        mock_get_desc.return_value = "описание: кнопка входа, поле email"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "test_cases": [
                    {
                        "Название": "Вход с валидными данными",
                        "Шаги": "1. Ввести email\n2. Ввести пароль\n3. Нажать кнопку",
                        "Ожидаемый результат": "Пользователь вошёл",
                        "Тип": "Позитивный",
                    }
                ]
            }
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={
                "task_text": "Проверить вход {{login}}",
                "fields": ["Название", "Шаги", "Ожидаемый результат"],
                "checklist_items": [
                    {
                        "id": "p-1",
                        "text": "Проверить вход с валидным email и паролем",
                        "category": "positive",
                        "area": "Авторизация",
                    }
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "test_cases" in data
        assert len(data["test_cases"]) == 1
        tc = data["test_cases"][0]
        assert tc["Тип"] == "Позитивный"

    @patch("backend.main.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_with_checklist_passes_context(self, mock_create, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {"test_cases": [{"Название": "Test", "Тип": "Негативный"}]}
        )
        mock_create.return_value = mock_response

        response = client.post(
            "/generate",
            json={
                "task_text": "test",
                "fields": ["Название"],
                "checklist_items": [
                    {
                        "id": "n-1",
                        "text": "Проверить вход с неверным паролем",
                        "category": "negative",
                        "area": "Авторизация",
                    }
                ],
            },
        )
        assert response.status_code == 200

        sent_messages = mock_create.call_args[1]["messages"]
        user_msg = [m for m in sent_messages if m["role"] == "user"][0]["content"]
        assert "неверным паролем" in user_msg
        assert "Авторизация" in user_msg

        system_msg = [m for m in sent_messages if m["role"] == "system"][0]["content"]
        assert "Тип" in system_msg
