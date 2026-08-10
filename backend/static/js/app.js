/**
 * Глобальное состояние приложения DocFlow QA.
 * Использует Alpine.store для реактивности и управления видами.
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('docflow', {
        // --- Аутентификация ---
        apiKey: localStorage.getItem('api_key') || '',
        loggedIn: false,

        // --- Навигация ---
        currentView: 'login', // 'login' | 'projects' | 'project'
        currentProject: null,
        mobileMenuOpen: false,

        // --- Данные ---
        projects: [],

        // --- Состояние загрузки и ошибки ---
        loading: false,
        error: '',
        toast: {
            message: '',
            type: 'info',
            show: false,
        },

        /**
         * Проверяем сохранённый ключ при старте.
         */
        async init() {
            if (this.apiKey) {
                await this.checkAuth();
            }
        },

        /**
         * Вход по API-ключу. Сохраняем ключ и проверяем его на бэкенде.
         */
        async login() {
            const key = this.apiKey.trim();
            if (!key) {
                this.error = 'Введите API-ключ';
                return;
            }
            this.error = '';
            this.apiKey = key;
            localStorage.setItem('api_key', key);
            DocFlowAPI.setApiKey(key);
            await this.checkAuth();
        },

        /**
         * Проверяет ключ и, если успешно, загружает проекты.
         */
        async checkAuth() {
            this.loading = true;
            this.error = '';
            try {
                DocFlowAPI.setApiKey(this.apiKey);
                await DocFlowAPI.checkAuth();
                this.loggedIn = true;
                this.currentView = 'projects';
                await this.loadProjects();
            } catch (err) {
                if (err.message === 'auth') {
                    this.error = 'Неверный или отсутствующий API-ключ';
                } else {
                    this.error = err.message || 'Не удалось подключиться к серверу';
                }
                this.logout();
            } finally {
                this.loading = false;
            }
        },

        /**
         * Выход: очищаем ключ и возвращаемся на экран логина.
         */
        logout() {
            this.apiKey = '';
            this.loggedIn = false;
            this.currentView = 'login';
            this.currentProject = null;
            this.projects = [];
            this.error = '';
            this.mobileMenuOpen = false;
            localStorage.removeItem('api_key');
        },

        /**
         * Загружает список проектов с сервера.
         */
        async loadProjects() {
            this.loading = true;
            try {
                this.projects = await DocFlowAPI.fetchProjects();
            } catch (err) {
                this.handleError(err);
            } finally {
                this.loading = false;
            }
        },

        /**
         * Переход к списку проектов.
         */
        showProjects() {
            this.currentProject = null;
            this.currentView = 'projects';
            this.mobileMenuOpen = false;
            this.loadProjects();
        },

        /**
         * Открыть детали проекта и подгрузить его ТЗ.
         */
        async openProject(project) {
            this.currentProject = { ...project, tz_text: '', tz_filename: '' };
            this.currentView = 'project';
            this.mobileMenuOpen = false;
            await this.loadProjectTz();
        },

        /**
         * Загрузить сохранённый текст ТЗ для текущего проекта.
         */
        async loadProjectTz() {
            if (!this.currentProject) return;
            this.loading = true;
            try {
                const data = await DocFlowAPI.fetchProjectTz(this.currentProject.id);
                this.currentProject.tz_text = data.tz_text || '';
                this.currentProject.tz_filename = data.tz_filename || '';
            } catch (err) {
                this.handleError(err);
            } finally {
                this.loading = false;
            }
        },

        /**
         * Централизованная обработка ошибок.
         */
        handleError(err) {
            if (err.message === 'auth') {
                this.logout();
            } else {
                this.error = err.message || 'Неизвестная ошибка';
            }
        },

        /**
         * Показать всплывающее уведомление.
         */
        showToast(message, type = 'info') {
            this.toast = { message, type, show: true };
            setTimeout(() => {
                this.toast.show = false;
            }, 3000);
        },
    });
});
