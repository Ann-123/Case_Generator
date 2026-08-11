/**
 * API-клиент для DocFlow QA.
 * Все запросы к FastAPI отправляются с заголовком X-API-Key.
 */
const API_BASE = ''; // относительно текущего origin

// Гарантируем, что глобальный объект существует до определения методов
window.DocFlowAPI = window.DocFlowAPI || {};

const DocFlowAPI = {
    apiKey: '',

    setApiKey(key) {
        this.apiKey = key;
    },

    _getHeaders() {
        return {
            'X-API-Key': this.apiKey,
        };
    },

    /**
     * Универсальный fetch-обработчик.
     * @param {string} method HTTP-метод
     * @param {string} endpoint относительный URL
     * @param {object|FormData|null} body тело запроса
     * @param {object} extraHeaders дополнительные заголовки
     * @returns {Promise<any>}
     */
    async _request(method, endpoint, body = null, extraHeaders = {}) {
        const url = `${API_BASE}${endpoint}`;
        const options = {
            method,
            headers: {
                ...this._getHeaders(),
                ...extraHeaders,
            },
        };

        if (body !== null) {
            if (body instanceof FormData) {
                // Content-Type браузер установит сам с boundary
                options.body = body;
            } else {
                options.headers['Content-Type'] = 'application/json';
                options.body = JSON.stringify(body);
            }
        }

        const response = await fetch(url, options);

        if (response.status === 401 || response.status === 403) {
            throw new Error('auth');
        }

        if (!response.ok) {
            let errorText = `Ошибка ${response.status}`;
            try {
                const data = await response.json();
                if (data.error) errorText = data.error;
            } catch {
                // игнорируем, если тело не JSON
            }
            throw new Error(errorText);
        }

        if (response.status === 204) return null;

        // Пустой ответ тоже допустим
        const text = await response.text();
        if (!text) return null;
        try {
            return JSON.parse(text);
        } catch {
            return text;
        }
    },

    // ---------- Аутентификация ----------
    async checkAuth() {
        return this._request('POST', '/auth/check');
    },

    // ---------- Проекты ----------
    async fetchProjects() {
        return this._request('GET', '/projects');
    },

    async createProject(name) {
        return this._request('POST', '/projects', { name });
    },

    async deleteProject(projectId) {
        return this._request('DELETE', `/projects/${projectId}`);
    },

    // ---------- ТЗ проекта ----------
    async fetchProjectTz(projectId) {
        return this._request('GET', `/projects/${projectId}/tz`);
    },

    async generateChtz(projectId) {
        return this._request('POST', `/projects/${projectId}/generate-chtz`);
    },

    async fetchRequirementsTree(projectId) {
        return this._request('GET', `/projects/${projectId}/requirements-tree`);
    },

    // ---------- Чек-листы ----------
    async generateChecklist(requirementId) {
        return this._request('POST', `/requirements/${requirementId}/checklist`);
    },

    async fetchChecklist(checklistId) {
        return this._request('GET', `/checklists/${checklistId}`);
    },

    async updateChecklist(checklistId, itemsJson) {
        return this._request('PUT', `/checklists/${checklistId}`, { items_json: itemsJson });
    },

    async deleteChecklist(checklistId) {
        return this._request('DELETE', `/checklists/${checklistId}`);
    },

    // ---------- Покрытие требования ----------
    async fetchRequirementCoverage(requirementId) {
        return this._request('GET', `/requirements/${requirementId}/coverage`);
    },

    // ---------- Тест-кейсы ----------
    async generateTestcase(checklistId, itemId) {
        return this._request('POST', `/checklists/${checklistId}/testcase/${itemId}`);
    },

    async updateTestcase(testcaseId, fields) {
        return this._request('PUT', `/testcases/${testcaseId}`, fields);
    },

    async deleteTestcase(testcaseId) {
        return this._request('DELETE', `/testcases/${testcaseId}`);
    },

    async uploadTz(projectId, formData) {
        const apiKey = this.apiKey || window.Alpine?.store('docflow')?.apiKey || localStorage.getItem('api_key') || '';
        const response = await fetch(`/projects/${projectId}/upload-tz`, {
            method: 'POST',
            headers: { 'X-API-Key': apiKey },
            body: formData,
        });

        if (response.status === 401 || response.status === 403) {
            throw new Error('auth');
        }

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: 'Ошибка загрузки ТЗ' }));
            throw new Error(err.detail || 'Ошибка загрузки ТЗ');
        }

        return response.json();
    },

    // ---------- Шаблоны документов ----------
    async fetchTemplates(projectId) {
        return this._request('GET', `/projects/${projectId}/templates`);
    },

    async uploadTemplate(projectId, formData) {
        return this._request('POST', `/projects/${projectId}/templates`, formData);
    },

    async deleteTemplate(projectId, docType) {
        return this._request('DELETE', `/projects/${projectId}/templates/${encodeURIComponent(docType)}`);
    },

    // ---------- Сборка и экспорт документов ----------
    async assembleDocument(projectId, docType) {
        return this._request('POST', `/projects/${projectId}/documents/${encodeURIComponent(docType)}/assemble`);
    },

    async updateSection(projectId, docType, sectionIndex, content) {
        return this._request('PUT', `/projects/${projectId}/documents/${encodeURIComponent(docType)}/sections/${sectionIndex}`, { content });
    },

    async exportDocument(projectId, docType) {
        const apiKey = this.apiKey || window.Alpine?.store('docflow')?.apiKey || localStorage.getItem('api_key') || '';
        const response = await fetch(`/projects/${projectId}/documents/${encodeURIComponent(docType)}/export`, {
            method: 'GET',
            headers: { 'X-API-Key': apiKey },
        });

        if (response.status === 401 || response.status === 403) {
            throw new Error('auth');
        }

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: 'Ошибка экспорта документа' }));
            throw new Error(err.detail || 'Ошибка экспорта документа');
        }

        return response.blob();
    },
};

window.DocFlowAPI = DocFlowAPI;
