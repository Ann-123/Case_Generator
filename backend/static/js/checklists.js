/**
 * Компоненты для просмотра требования, чек-листа и тест-кейсов.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('requirementView', () => ({
        // --- Данные ---
        coverage: null,
        checklist: null,
        testcases: {},
        loadingCoverage: false,

        // --- Редактирование чек-листа ---
        editingChecklist: false,
        positiveItems: [],
        negativeItems: [],
        checklistEditCounter: 1,

        // --- Развёрнутые пункты (id → true/false) ---
        expandedItems: {},

        // --- Редактирование тест-кейса ---
        editingTestcase: null,

        /**
         * При появлении требования загружаем его покрытие.
         */
        init() {
            this.$watch('$store.docflow.selectedRequirement', (req) => {
                if (req) {
                    this.loadCoverage();
                } else {
                    this.resetCoverage();
                }
            });
        },

        /**
         * Сбросить локальные данные покрытия.
         */
        resetCoverage() {
            this.coverage = null;
            this.checklist = null;
            this.testcases = {};
            this.editingChecklist = false;
            this.editingTestcase = null;
            this.expandedItems.clear();
        },

        /**
         * Загрузить покрытие требования: чек-листы и тест-кейсы.
         */
        async loadCoverage() {
            const req = this.$store.docflow.selectedRequirement;
            if (!req) return;

            this.loadingCoverage = true;
            this.editingChecklist = false;
            this.editingTestcase = null;
            try {
                const data = await DocFlowAPI.fetchRequirementCoverage(req.id);
                this.coverage = data;
                this.checklist = data.checklists && data.checklists.length > 0 ? data.checklists[0] : null;
                this.buildTestcaseMap(data.testcases || []);
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.loadingCoverage = false;
            }
        },

        /**
         * Построить map тест-кейсов по id пункта чек-листа.
         */
        buildTestcaseMap(testcases) {
            const map = {};
            for (const tc of testcases) {
                if (tc.checklist_item_id) {
                    map[tc.checklist_item_id] = tc;
                }
            }
            this.testcases = map;
        },

        /**
         * Тест-кейс для пункта чек-листа.
         */
        testcaseFor(itemId) {
            return this.testcases[itemId] || null;
        },

        /**
         * Развернуть/свернуть пункт.
         */
        toggleItem(itemId) {
            this.expandedItems[itemId] = !this.expandedItems[itemId];
        },

        /**
         * Пункт развёрнут?
         */
        isExpanded(itemId) {
            return !!this.expandedItems[itemId];
        },

        /**
         * Иконка категории пункта: позитивная или негативная.
         */
        categoryIcon(category) {
            return category === 'positive' ? '✓' : '✗';
        },

        /**
         * Цвет категории пункта.
         */
        categoryColor(category) {
            return category === 'positive' ? 'bg-sage-400' : 'bg-bloom-400';
        },

        /**
         * Сгенерировать чек-лист для текущего требования.
         */
        async generateChecklist() {
            const req = this.$store.docflow.selectedRequirement;
            if (!req) return;

            this.$store.docflow.loading = true;
            try {
                await DocFlowAPI.generateChecklist(req.id);
                this.$store.docflow.showToast('Чек-лист сгенерирован', 'success');
                await this.loadCoverage();
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.$store.docflow.loading = false;
            }
        },

        /**
         * Сгенерировать тест-кейс для пункта чек-листа.
         */
        async generateTestcase(itemId) {
            if (!this.checklist) return;
            this.$store.docflow.loading = true;
            try {
                await DocFlowAPI.generateTestcase(this.checklist.id, itemId);
                this.$store.docflow.showToast('Тест-кейс сгенерирован', 'success');
                await this.loadCoverage();
                this.expandedItems.add(itemId);
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.$store.docflow.loading = false;
            }
        },

        // ---------- Редактирование чек-листа ----------

        /**
         * Перейти в режим редактирования чек-листа.
         */
        startEditingChecklist() {
            if (!this.checklist) return;
            const items = this.checklist.items || {};
            this.positiveItems = this.ensureIds(items.positive || [], 'positive');
            this.negativeItems = this.ensureIds(items.negative || [], 'negative');
            this.editingChecklist = true;
        },

        /**
         * Убедиться, что у каждого пункта есть id.
         */
        ensureIds(items, category) {
            return items.map((item, idx) => {
                if (item.id) return { ...item };
                const prefix = category === 'positive' ? 'p' : 'n';
                return { ...item, id: `${prefix}-existing-${idx}-${Date.now()}` };
            });
        },

        /**
         * Добавить новый пункт в категорию.
         */
        addItem(category) {
            const prefix = category === 'positive' ? 'p' : 'n';
            const newItem = {
                id: `${prefix}-new-${this.checklistEditCounter++}-${Date.now()}`,
                text: '',
            };
            if (category === 'positive') {
                this.positiveItems.push(newItem);
            } else {
                this.negativeItems.push(newItem);
            }
        },

        /**
         * Удалить пункт из категории.
         */
        removeItem(category, index) {
            if (category === 'positive') {
                this.positiveItems.splice(index, 1);
            } else {
                this.negativeItems.splice(index, 1);
            }
        },

        /**
         * Отменить редактирование чек-листа.
         */
        cancelEditChecklist() {
            this.editingChecklist = false;
        },

        /**
         * Сохранить изменения чек-листа.
         */
        async saveChecklist() {
            if (!this.checklist) return;

            const itemsJson = {
                positive: this.positiveItems.map(item => ({ id: item.id, text: item.text })),
                negative: this.negativeItems.map(item => ({ id: item.id, text: item.text })),
            };

            this.$store.docflow.loading = true;
            try {
                await DocFlowAPI.updateChecklist(this.checklist.id, itemsJson);
                this.$store.docflow.showToast('Чек-лист сохранён', 'success');
                this.editingChecklist = false;
                await this.loadCoverage();
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.$store.docflow.loading = false;
            }
        },

        /**
         * Удалить чек-лист.
         */
        async deleteChecklist() {
            if (!this.checklist) return;
            if (!confirm('Удалить чек-лист и все связанные тест-кейсы?')) return;

            this.$store.docflow.loading = true;
            try {
                await DocFlowAPI.deleteChecklist(this.checklist.id);
                this.$store.docflow.showToast('Чек-лист удалён', 'success');
                await this.loadCoverage();
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.$store.docflow.loading = false;
            }
        },

        // ---------- Редактирование тест-кейса ----------

        /**
         * Начать редактирование тест-кейса.
         */
        editTestcase(tc) {
            this.editingTestcase = {
                id: tc.id,
                title: tc.title || '',
                steps: tc.steps || '',
                expected_result: tc.expected_result || '',
                include_in_pmi: !!tc.include_in_pmi,
            };
        },

        /**
         * Отменить редактирование тест-кейса.
         */
        cancelEditTestcase() {
            this.editingTestcase = null;
        },

        /**
         * Сохранить тест-кейс.
         */
        async saveTestcase() {
            if (!this.editingTestcase) return;
            this.$store.docflow.loading = true;
            try {
                await DocFlowAPI.updateTestcase(this.editingTestcase.id, {
                    title: this.editingTestcase.title,
                    steps: this.editingTestcase.steps,
                    expected_result: this.editingTestcase.expected_result,
                    include_in_pmi: this.editingTestcase.include_in_pmi,
                });
                this.$store.docflow.showToast('Тест-кейс сохранён', 'success');
                this.editingTestcase = null;
                await this.loadCoverage();
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.$store.docflow.loading = false;
            }
        },

        /**
         * Переключить флаг "Включить в ПМИ".
         */
        async togglePmi(tc) {
            this.$store.docflow.loading = true;
            try {
                await DocFlowAPI.updateTestcase(tc.id, {
                    include_in_pmi: !tc.include_in_pmi,
                });
                this.$store.docflow.showToast('Флаг ПМИ обновлён', 'success');
                await this.loadCoverage();
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.$store.docflow.loading = false;
            }
        },

        /**
         * Удалить тест-кейс.
         */
        async deleteTestcase(tc) {
            if (!confirm('Удалить тест-кейс?')) return;
            this.$store.docflow.loading = true;
            try {
                await DocFlowAPI.deleteTestcase(tc.id);
                this.$store.docflow.showToast('Тест-кейс удалён', 'success');
                await this.loadCoverage();
            } catch (err) {
                this.$store.docflow.handleError(err);
            } finally {
                this.$store.docflow.loading = false;
            }
        },

        /**
         * Разбить текст шагов на массив строк.
         */
        splitSteps(steps) {
            if (!steps) return [];
            return steps.split('\n').filter(line => line.trim() !== '');
        },
    }));
});
