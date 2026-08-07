import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


CHECKLIST_RESPONSE = {
    "checklist": {
        "positive": [
            {"id": "p-1", "text": "Проверить успешную авторизацию по логину и паролю"},
            {"id": "p-2", "text": "Проверить успешную авторизацию по SMS-коду"},
        ],
        "negative": [
            {"id": "n-1", "text": "Проверить ошибку при неверном пароле"},
        ],
    }
}


TESTCASE_RESPONSE = {
    "title": "Успешная авторизация по логину и паролю",
    "steps": [
        "Шаг 1: Открыть страницу авторизации",
        "Шаг 2: Ввести корректный логин и пароль",
        "Шаг 3: Нажать кнопку 'Войти'",
    ],
    "expected_result": "Пользователь успешно авторизован и перенаправлен на главную страницу",
}


def _make_llm_mock(content):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    return mock_response


@pytest.fixture(scope="module")
def client():
    import tempfile as tmp
    import backend.database as db_module

    tmp_db = tmp.mkstemp(suffix=".db")[1]
    db_module.DB_PATH = tmp_db
    db_module.init_db()

    from backend.main import app, limiter

    limiter.enabled = False

    client = TestClient(app)
    client.headers.update({"X-API-Key": "test-api-key-for-tests"})
    yield client

    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


@pytest.fixture
def requirement(client):
    """Создаёт проект и требование для тестов."""
    project_resp = client.post("/projects", json={"name": "Проект для чек-листов"})
    project_id = project_resp.json()["id"]

    from backend.database import create_requirement

    req_id = create_requirement(
        project_id=project_id,
        title="Авторизация пользователя",
        description="Пользователь должен авторизоваться по логину/паролю или SMS",
        code="ФТ_1.1",
        parent_id=None,
        section_path="1. Авторизация",
        sort_order=0,
    )
    return req_id


class TestGenerateChecklist:
    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_checklist_success(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))

        response = client.post(f"/requirements/{requirement}/checklist")
        assert response.status_code == 200
        data = response.json()
        assert data["requirement_id"] == requirement
        assert "id" in data
        assert data["items"]["positive"][0]["id"] == "p-1"
        assert data["items"]["negative"][0]["id"] == "n-1"

    def test_generate_checklist_requirement_not_found(self, client):
        response = client.post("/requirements/99999/checklist")
        assert response.status_code == 404

    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_checklist_invalid_json(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock("Это не JSON")

        response = client.post(f"/requirements/{requirement}/checklist")
        assert response.status_code == 500
        assert "JSON" in response.json()["error"]


class TestGetUpdateDeleteChecklist:
    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_get_checklist(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        create_resp = client.post(f"/requirements/{requirement}/checklist")
        checklist_id = create_resp.json()["id"]

        response = client.get(f"/checklists/{checklist_id}")
        assert response.status_code == 200
        assert response.json()["id"] == checklist_id

    def test_get_checklist_not_found(self, client):
        response = client.get("/checklists/99999")
        assert response.status_code == 404

    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_update_checklist(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        create_resp = client.post(f"/requirements/{requirement}/checklist")
        checklist_id = create_resp.json()["id"]

        new_items = {
            "positive": [{"id": "p-1", "text": "Обновлённая проверка"}],
            "negative": [],
        }
        response = client.put(f"/checklists/{checklist_id}", json={"items_json": new_items})
        assert response.status_code == 200
        data = response.json()
        assert data["items"]["positive"][0]["text"] == "Обновлённая проверка"
        assert data["items"]["negative"] == []

    def test_update_checklist_not_found(self, client):
        response = client.put("/checklists/99999", json={"items_json": {"positive": []}})
        assert response.status_code == 404

    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_delete_checklist(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        create_resp = client.post(f"/requirements/{requirement}/checklist")
        checklist_id = create_resp.json()["id"]

        response = client.delete(f"/checklists/{checklist_id}")
        assert response.status_code == 200

        response = client.get(f"/checklists/{checklist_id}")
        assert response.status_code == 404

    def test_delete_checklist_not_found(self, client):
        response = client.delete("/checklists/99999")
        assert response.status_code == 404


class TestGenerateTestcase:
    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_testcase_success(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        create_resp = client.post(f"/requirements/{requirement}/checklist")
        checklist_id = create_resp.json()["id"]

        mock_create.return_value = _make_llm_mock(json.dumps(TESTCASE_RESPONSE, ensure_ascii=False))
        response = client.post(f"/checklists/{checklist_id}/testcase/p-1")
        assert response.status_code == 200
        data = response.json()
        assert data["checklist_id"] == checklist_id
        assert data["checklist_item_id"] == "p-1"
        assert data["requirement_id"] == requirement
        assert data["title"] == TESTCASE_RESPONSE["title"]
        assert "Шаг 1:" in data["steps"]
        assert data["include_in_pmi"] is False

    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_generate_testcase_item_not_found(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        create_resp = client.post(f"/requirements/{requirement}/checklist")
        checklist_id = create_resp.json()["id"]

        response = client.post(f"/checklists/{checklist_id}/testcase/unknown")
        assert response.status_code == 400

    def test_generate_testcase_checklist_not_found(self, client):
        response = client.post("/checklists/99999/testcase/p-1")
        assert response.status_code == 404


class TestUpdateDeleteTestcase:
    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_update_testcase(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        create_resp = client.post(f"/requirements/{requirement}/checklist")
        checklist_id = create_resp.json()["id"]

        mock_create.return_value = _make_llm_mock(json.dumps(TESTCASE_RESPONSE, ensure_ascii=False))
        testcase_resp = client.post(f"/checklists/{checklist_id}/testcase/p-1")
        testcase_id = testcase_resp.json()["id"]

        response = client.put(
            f"/testcases/{testcase_id}",
            json={"title": "Новое название", "include_in_pmi": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Новое название"
        assert data["include_in_pmi"] is True

    def test_update_testcase_not_found(self, client):
        response = client.put("/testcases/99999", json={"title": "Новое название"})
        assert response.status_code == 404

    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_delete_testcase(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        create_resp = client.post(f"/requirements/{requirement}/checklist")
        checklist_id = create_resp.json()["id"]

        mock_create.return_value = _make_llm_mock(json.dumps(TESTCASE_RESPONSE, ensure_ascii=False))
        testcase_resp = client.post(f"/checklists/{checklist_id}/testcase/p-1")
        testcase_id = testcase_resp.json()["id"]

        response = client.delete(f"/testcases/{testcase_id}")
        assert response.status_code == 200

        response = client.get(f"/testcases/{testcase_id}")
        assert response.status_code == 404

    def test_delete_testcase_not_found(self, client):
        response = client.delete("/testcases/99999")
        assert response.status_code == 404


class TestCoverage:
    @patch("backend.checklists.client.chat.completions.create", new_callable=AsyncMock)
    def test_get_coverage(self, mock_create, client, requirement):
        mock_create.return_value = _make_llm_mock(json.dumps(CHECKLIST_RESPONSE, ensure_ascii=False))
        client.post(f"/requirements/{requirement}/checklist")

        response = client.get(f"/requirements/{requirement}/coverage")
        assert response.status_code == 200
        data = response.json()
        assert data["requirement"]["id"] == requirement
        assert data["summary"]["checklists_count"] == 1
        assert data["summary"]["testcases_count"] == 0
        assert data["summary"]["pmi_testcases_count"] == 0

    def test_get_coverage_requirement_not_found(self, client):
        response = client.get("/requirements/99999/coverage")
        assert response.status_code == 404
