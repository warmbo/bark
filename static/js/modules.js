// Module Utilities - Common JavaScript functionality for all modules

/**
 * Standardized API request handler with error handling and loading states
 */
class ModuleAPI {
    constructor(moduleName) {
        this.moduleName = moduleName;
        this.baseUrl = `/api/${moduleName}`;
    }

    /**
     * Make an API request with standardized error handling
     */
    async request(action, options = {}) {
        const {
            method = 'GET',
            data = null,
            timeout = 10000,
            loadingElement = null,
            resultElement = null
        } = options;

        // Show loading state
        if (loadingElement) {
            this.setLoadingState(loadingElement, true);
        }
        if (resultElement) {
            this.setResultState(resultElement, 'loading', 'Loading...');
        }

        try {
            const requestOptions = {
                method,
                headers: {
                    'Content-Type': 'application/json'
                }
            };

            if (data && method !== 'GET') {
                requestOptions.body = JSON.stringify(data);
            }

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), timeout);

            const response = await fetch(`${this.baseUrl}/${action}`, {
                ...requestOptions,
                signal: controller.signal
            });

            clearTimeout(timeoutId);

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || `HTTP ${response.status}`);
            }

            // Show success state
            if (resultElement) {
                this.setResultState(resultElement, 'success', result);
            }

            return result;

        } catch (error) {
            const errorMessage = error.name === 'AbortError' 
                ? 'Request timed out' 
                : error.message;

            // Show error state
            if (resultElement) {
                this.setResultState(resultElement, 'error', errorMessage);
            }

            console.error(`API Error (${this.moduleName}/${action}):`, error);
            throw error;

        } finally {
            // Hide loading state
            if (loadingElement) {
                this.setLoadingState(loadingElement, false);
            }
        }
    }

    /**
     * Set loading state for an element
     */
    setLoadingState(element, isLoading) {
        if (!element) return;

        if (isLoading) {
            element.classList.add('loading');
            element.disabled = true;
            
            // Store original content and show loading spinner
            if (element.tagName === 'BUTTON') {
                element.dataset.originalText = element.innerHTML;
                element.innerHTML = '<span class="loading-spinner"></span> Loading...';
            }
        } else {
            element.classList.remove('loading');
            element.disabled = false;
            
            // Restore original content
            if (element.dataset.originalText) {
                element.innerHTML = element.dataset.originalText;
                delete element.dataset.originalText;
            }
        }
    }

    /**
     * Set result state for display elements
     */
    setResultState(element, state, content) {
        if (!element) return;

        // Clear existing state classes
        element.classList.remove('loading', 'error', 'success');
        
        // Add new state class
        element.classList.add(state);

        // Set content based on type
        if (typeof content === 'string') {
            element.textContent = content;
        } else if (typeof content === 'object') {
            element.textContent = JSON.stringify(content, null, 2);
        }

        // Auto-hide success messages after 3 seconds
        if (state === 'success') {
            setTimeout(() => {
                element.classList.remove('success');
            }, 3000);
        }
    }
}

/**
 * Form handler for module forms
 */
class ModuleForm {
    constructor(formElement, api) {
        this.form = formElement;
        this.api = api;
        this.setupEventListeners();
    }

    setupEventListeners() {
        if (!this.form) return;

        this.form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleSubmit();
        });

        // Auto-submit on Enter for single input forms
        const inputs = this.form.querySelectorAll('input[type="text"], input[type="email"]');
        if (inputs.length === 1) {
            inputs[0].addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.handleSubmit();
                }
            });
        }
    }

    async handleSubmit() {
        const formData = this.getFormData();
        const submitButton = this.form.querySelector('button[type="submit"], .btn-primary');
        const resultElement = this.form.querySelector('.api-result');

        try {
            await this.api.request('submit', {
                method: 'POST',
                data: formData,
                loadingElement: submitButton,
                resultElement
            });

            // Reset form on success
            this.form.reset();

        } catch (error) {
            // Error already handled by API class
        }
    }

    getFormData() {
        const data = {};
        const formData = new FormData(this.form);
        
        for (const [key, value] of formData.entries()) {
            data[key] = value;
        }

        return data;
    }

    setFieldValue(name, value) {
        const field = this.form.querySelector(`[name="${name}"]`);
        if (field) {
            field.value = value;
        }
    }

    getFieldValue(name) {
        const field = this.form.querySelector(`[name="${name}"]`);
        return field ? field.value : null;
    }
}

/**
 * Server and channel selector utility
 */
class ServerChannelSelector {
    constructor(serverSelectId, channelSelectId, api) {
        this.serverSelect = document.getElementById(serverSelectId);
        this.channelSelect = document.getElementById(channelSelectId);
        this.api = api;
        
        this.setupEventListeners();
        this.loadServers();
    }

    setupEventListeners() {
        if (this.serverSelect) {
            this.serverSelect.addEventListener('change', () => {
                this.loadChannels(this.serverSelect.value);
            });
        }
    }

    async loadServers() {
        if (!this.serverSelect) return;

        try {
            const data = await this.api.request('get_servers');
            
            this.serverSelect.innerHTML = '<option value="">Select server</option>';
            
            if (data.servers) {
                data.servers.forEach(server => {
                    const option = document.createElement('option');
                    option.value = server.id;
                    option.textContent = server.name;
                    this.serverSelect.appendChild(option);
                });
            }
        } catch (error) {
            this.serverSelect.innerHTML = '<option value="">Error loading servers</option>';
        }
    }

    async loadChannels(serverId) {
        if (!this.channelSelect || !serverId) {
            if (this.channelSelect) {
                this.channelSelect.innerHTML = '<option value="">Select a server first</option>';
                this.channelSelect.disabled = true;
            }
            return;
        }

        try {
            const data = await this.api.request('get_channels', {
                method: 'GET',
                data: { server_id: serverId }
            });

            this.channelSelect.innerHTML = '<option value="">Select channel</option>';
            
            if (data.channels) {
                data.channels.forEach(channel => {
                    const option = document.createElement('option');
                    option.value = channel.id;
                    option.textContent = '#' + channel.name;
                    this.channelSelect.appendChild(option);
                });
            }
            
            this.channelSelect.disabled = false;
            
        } catch (error) {
            this.channelSelect.innerHTML = '<option value="">Error loading channels</option>';
            this.channelSelect.disabled = true;
        }
    }

    getSelectedServer() {
        return this.serverSelect ? this.serverSelect.value : null;
    }

    getSelectedChannel() {
        return this.channelSelect ? this.channelSelect.value : null;
    }
}

/**
 * Notification system for user feedback
 */
class NotificationSystem {
    constructor() {
        this.container = this.createContainer();
    }

    createContainer() {
        let container = document.getElementById('notification-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notification-container';
            container.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 1000;
                display: flex;
                flex-direction: column;
                gap: 10px;
                pointer-events: none;
            `;
            document.body.appendChild(container);
        }
        return container;
    }

    show(message, type = 'info', duration = 3000) {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.style.cssText = `
            background: var(--glass-bg);
            backdrop-filter: var(--blur);
            border: 1px solid var(--glass-border);
            border-radius: 8px;
            padding: 12px 16px;
            color: var(--text);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            pointer-events: auto;
            max-width: 300px;
            transform: translateX(100%);
            transition: transform 0.3s ease;
        `;

        // Type-specific styling
        if (type === 'success') {
            notification.style.borderColor = '#10b981';
            notification.style.color = '#10b981';
        } else if (type === 'error') {
            notification.style.borderColor = '#ef4444';
            notification.style.color = '#ef4444';
        } else if (type === 'warning') {
            notification.style.borderColor = '#f59e0b';
            notification.style.color = '#f59e0b';
        }

        notification.textContent = message;
        this.container.appendChild(notification);

        // Animate in
        setTimeout(() => {
            notification.style.transform = 'translateX(0)';
        }, 10);

        // Auto remove
        setTimeout(() => {
            this.remove(notification);
        }, duration);

        // Click to dismiss
        notification.addEventListener('click', () => {
            this.remove(notification);
        });

        return notification;
    }

    remove(notification) {
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }

    success(message, duration) {
        return this.show(message, 'success', duration);
    }

    error(message, duration) {
        return this.show(message, 'error', duration);
    }

    warning(message, duration) {
        return this.show(message, 'warning', duration);
    }
}

/**
 * Data table utility for displaying structured data
 */
class DataTable {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            searchable: true,
            sortable: true,
            pagination: true,
            pageSize: 10,
            ...options
        };
        this.data = [];
        this.filteredData = [];
        this.currentPage = 0;
        this.sortColumn = null;
        this.sortDirection = 'asc';
    }

    setData(data) {
        this.data = data;
        this.filteredData = [...data];
        this.currentPage = 0;
        this.render();
    }

    render() {
        if (!this.container || !this.data.length) return;

        this.container.innerHTML = '';

        // Search box
        if (this.options.searchable) {
            this.renderSearch();
        }

        // Table
        this.renderTable();

        // Pagination
        if (this.options.pagination) {
            this.renderPagination();
        }
    }

    renderSearch() {
        const searchContainer = document.createElement('div');
        searchContainer.className = 'data-table-search mb-2';
        
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.placeholder = 'Search...';
        searchInput.className = 'form-control';
        searchInput.addEventListener('input', (e) => {
            this.filter(e.target.value);
        });

        searchContainer.appendChild(searchInput);
        this.container.appendChild(searchContainer);
    }

    renderTable() {
        if (!this.filteredData.length) {
            this.container.innerHTML += '<p class="text-muted text-center">No data available</p>';
            return;
        }

        const table = document.createElement('table');
        table.className = 'data-table';
        table.style.cssText = `
            width: 100%;
            border-collapse: collapse;
            background: var(--surface);
            border-radius: 8px;
            overflow: hidden;
        `;

        // Header
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        headerRow.style.cssText = 'background: var(--background);';

        const columns = Object.keys(this.filteredData[0]);
        columns.forEach(column => {
            const th = document.createElement('th');
            th.textContent = column.charAt(0).toUpperCase() + column.slice(1);
            th.style.cssText = `
                padding: 12px;
                text-align: left;
                color: var(--text);
                border-bottom: 1px solid var(--border);
                cursor: pointer;
            `;

            if (this.options.sortable) {
                th.addEventListener('click', () => this.sort(column));
                th.style.cursor = 'pointer';
            }

            headerRow.appendChild(th);
        });

        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Body
        const tbody = document.createElement('tbody');
        const startIndex = this.currentPage * this.options.pageSize;
        const endIndex = startIndex + this.options.pageSize;
        const pageData = this.filteredData.slice(startIndex, endIndex);

        pageData.forEach(row => {
            const tr = document.createElement('tr');
            tr.style.cssText = 'border-bottom: 1px solid var(--border);';

            columns.forEach(column => {
                const td = document.createElement('td');
                td.textContent = row[column];
                td.style.cssText = `
                    padding: 12px;
                    color: var(--text-muted);
                `;
                tr.appendChild(td);
            });

            tbody.appendChild(tr);
        });

        table.appendChild(tbody);
        this.container.appendChild(table);
    }

    renderPagination() {
        const totalPages = Math.ceil(this.filteredData.length / this.options.pageSize);
        if (totalPages <= 1) return;

        const paginationContainer = document.createElement('div');
        paginationContainer.className = 'data-table-pagination mt-2';
        paginationContainer.style.cssText = `
            display: flex;
            justify-content: center;
            gap: 8px;
            align-items: center;
        `;

        // Previous button
        const prevBtn = this.createPaginationButton('Previous', () => {
            if (this.currentPage > 0) {
                this.currentPage--;
                this.render();
            }
        });
        prevBtn.disabled = this.currentPage === 0;
        paginationContainer.appendChild(prevBtn);

        // Page numbers
        for (let i = 0; i < totalPages; i++) {
            const pageBtn = this.createPaginationButton(i + 1, () => {
                this.currentPage = i;
                this.render();
            });
            
            if (i === this.currentPage) {
                pageBtn.style.background = 'var(--primary)';
                pageBtn.style.color = 'white';
            }
            
            paginationContainer.appendChild(pageBtn);
        }

        // Next button
        const nextBtn = this.createPaginationButton('Next', () => {
            if (this.currentPage < totalPages - 1) {
                this.currentPage++;
                this.render();
            }
        });
        nextBtn.disabled = this.currentPage === totalPages - 1;
        paginationContainer.appendChild(nextBtn);

        this.container.appendChild(paginationContainer);
    }

    createPaginationButton(text, onClick) {
        const button = document.createElement('button');
        button.textContent = text;
        button.className = 'btn btn-small btn-secondary';
        button.addEventListener('click', onClick);
        return button;
    }

    filter(searchTerm) {
        if (!searchTerm) {
            this.filteredData = [...this.data];
        } else {
            this.filteredData = this.data.filter(row =>
                Object.values(row).some(value =>
                    String(value).toLowerCase().includes(searchTerm.toLowerCase())
                )
            );
        }
        this.currentPage = 0;
        this.render();
    }

    sort(column) {
        if (this.sortColumn === column) {
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortColumn = column;
            this.sortDirection = 'asc';
        }

        this.filteredData.sort((a, b) => {
            const aVal = a[column];
            const bVal = b[column];

            if (typeof aVal === 'number' && typeof bVal === 'number') {
                return this.sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
            }

            const aStr = String(aVal).toLowerCase();
            const bStr = String(bVal).toLowerCase();
            
            if (this.sortDirection === 'asc') {
                return aStr.localeCompare(bStr);
            } else {
                return bStr.localeCompare(aStr);
            }
        });

        this.render();
    }
}

// Global instances
const notifications = new NotificationSystem();

// Global utility functions
function initializeModule(moduleName) {
    const api = new ModuleAPI(moduleName);
    
    // Initialize common components
    const forms = document.querySelectorAll(`#${moduleName} form`);
    forms.forEach(form => new ModuleForm(form, api));
    
    // Initialize Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    return api;
}

// Export for use in modules
window.ModuleAPI = ModuleAPI;
window.ModuleForm = ModuleForm;
window.ServerChannelSelector = ServerChannelSelector;
window.NotificationSystem = NotificationSystem;
window.DataTable = DataTable;
window.notifications = notifications;
window.initializeModule = initializeModule;