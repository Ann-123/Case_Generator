/**
 * Компоненты для работы с деревом требований (ЧТЗ).
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('requirementsTree', () => ({
        // Объект id → true/false для развёрнутых узлов
        // (используем объект вместо Set для корректной реактивности Alpine.js)
        expandedNodes: {},

        /**
         * Развернуть/свернуть узел дерева.
         */
        toggleNode(node) {
            if (!node.children?.length) return;
            this.expandedNodes[node.id] = !this.expandedNodes[node.id];
        },

        /**
         * Узел раскрыт?
         */
        isExpanded(node) {
            return !!this.expandedNodes[node.id];
        },

        /**
         * Построить плоский список видимых узлов с учётом глубины.
         */
        visibleNodes() {
            const nodes = [];
            const walk = (tree, depth) => {
                for (const node of tree) {
                    nodes.push({ ...node, depth });
                    if (this.isExpanded(node) && node.children?.length) {
                        walk(node.children, depth + 1);
                    }
                }
            };
            walk(this.$store.docflow.requirementsTree, 0);
            return nodes;
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
         * Подсветка активного узла.
         */
        isNodeActive(node) {
            const store = this.$store.docflow;
            if (node.code) {
                return store.selectedRequirement && store.selectedRequirement.id === node.id;
            }
            return store.selectedSection && store.selectedSection.id === node.id;
        },

        /**
         * Обработчик клика по узлу дерева.
         */
        handleNodeClick(node) {
            if (node.children?.length) {
                this.toggleNode(node);
            }
            if (node.code) {
                this.selectRequirement(node);
            } else {
                this.selectSection(node);
            }
        },
    }));
});
