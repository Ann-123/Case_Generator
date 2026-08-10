/**
 * Компоненты Alpine.js для управления проектами и загрузки ТЗ.
 */
document.addEventListener('alpine:init', () => {
    // ---------- Список проектов + модальное окно создания ----------
    Alpine.data('projectList', () => ({
        createModalOpen: false,
        newProjectName: '',

        /**
         * Открыть модальное окно создания проекта.
         */
        openCreateModal() {
            this.createModalOpen = true;
            this.newProjectName = '';
            // Фокус на поле ввода после открытия окна
            this.$nextTick(() => {
                this.$refs.newProjectInput?.focus();
            });
        },

        /**
         * Закрыть модальное окно.
         */
        closeCreateModal() {
            this.createModalOpen = false;
            this.newProjectName = '';
        },

        /**
         * Создать новый проект.
         */
        async createProject() {
            const name = this.newProjectName.trim();
            if (!name) return;

            const store = this.$store.docflow;
            store.loading = true;
            store.error = '';
            try {
                const project = await DocFlowAPI.createProject(name);
                store.projects.unshift(project);
                store.showToast('Проект создан', 'success');
                this.closeCreateModal();
            } catch (err) {
                store.handleError(err);
            } finally {
                store.loading = false;
            }
        },

        /**
         * Удалить проект (пока с подтверждением).
         */
        async deleteProject(project) {
            if (!confirm(`Удалить проект «${project.name}»?`)) return;

            const store = this.$store.docflow;
            store.loading = true;
            try {
                await DocFlowAPI.deleteProject(project.id);
                store.projects = store.projects.filter(p => p.id !== project.id);
                store.showToast('Проект удалён', 'success');
            } catch (err) {
                store.handleError(err);
            } finally {
                store.loading = false;
            }
        },
    }));

    // ---------- Детали проекта: загрузка ТЗ и генерация ЧТЗ ----------
    Alpine.data('projectDetail', () => ({
        tzText: '',
        tzFile: null,
        tzFileName: '',
        tzMode: 'text', // 'text' | 'file'

        /**
         * При монтировании компонента подтягиваем текущий текст ТЗ.
         */
        init() {
            this.tzText = this.$store.docflow.currentProject?.tz_text || '';
            this.tzFile = null;
            this.tzFileName = this.$store.docflow.currentProject?.tz_filename || '';
        },

        /**
         * Обработка выбора файла .docx.
         */
        handleFileChange(event) {
            const file = event.target.files[0];
            if (file) {
                this.tzFile = file;
                this.tzFileName = file.name;
            } else {
                this.tzFile = null;
                this.tzFileName = '';
            }
        },

        /**
         * Сохранить ТЗ на сервер (текст или .docx).
         */
        async uploadTZ() {
            const store = this.$store.docflow;
            const projectId = store.currentProject?.id;
            if (!projectId) return;

            const formData = new FormData();
            if (this.tzFile) {
                formData.append('file', this.tzFile);
            } else {
                if (!this.tzText.trim()) {
                    store.error = 'Введите текст ТЗ или выберите файл .docx';
                    return;
                }
                formData.append('tz_text', this.tzText);
            }

            store.loading = true;
            store.error = '';
            try {
                const data = await DocFlowAPI.uploadProjectTz(projectId, formData);
                store.currentProject.tz_text = data.tz_text || '';
                store.currentProject.tz_filename = data.tz_filename || '';
                this.tzText = data.tz_text || '';
                this.tzFile = null;
                store.showToast('ТЗ сохранено', 'success');
            } catch (err) {
                store.handleError(err);
            } finally {
                store.loading = false;
            }
        },

        /**
         * Сгенерировать ЧТЗ из сохранённого ТЗ.
         */
        async generateChtz() {
            const store = this.$store.docflow;
            const projectId = store.currentProject?.id;
            if (!projectId) return;

            store.loading = true;
            store.error = '';
            try {
                await DocFlowAPI.generateChtz(projectId);
                store.showToast('ЧТЗ успешно сгенерировано', 'success');
            } catch (err) {
                store.handleError(err);
            } finally {
                store.loading = false;
            }
        },
    }));
});
