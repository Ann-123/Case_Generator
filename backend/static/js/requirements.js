/**
 * Компоненты для работы с деревом требований (ЧТЗ).
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('requirementsTree', () => ({
        // Объект id → true/false для развёрнутых разделов
        // (используем объект вместо Set для корректной реактивности Alpine.js)
        expandedSections: {},

        /**
         * Развернуть/свернуть раздел.
         */
        toggleSection(section) {
            this.expandedSections[section.id] = !this.expandedSections[section.id];
        },

        /**
         * Раздел раскрыт?
         */
        isExpanded(section) {
            return !!this.expandedSections[section.id];
        },

        /**
         * Обновить дерево с сервера.
         */
        async refreshTree() {
            const store = this.$store.docflow;
            await store.loadRequirementsTree();
        },

        /**
         * Сгенерировать ЧТЗ повторно.
         */
        async regenerateChtz() {
            const store = this.$store.docflow;
            await store.generateChtz();
        },

        /**
         * Выбрать раздел.
         */
        selectSection(section) {
            this.$store.docflow.selectSection(section);
        },

        /**
         * Выбрать требование.
         */
        selectRequirement(req) {
            this.$store.docflow.selectRequirement(req);
        },

        /**
         * Подсветка активного раздела.
         */
        isSectionActive(section) {
            const store = this.$store.docflow;
            return store.selectedSection && store.selectedSection.id === section.id;
        },

        /**
         * Подсветка активного требования.
         */
        isRequirementActive(req) {
            const store = this.$store.docflow;
            return store.selectedRequirement && store.selectedRequirement.id === req.id;
        },
    }));
});
