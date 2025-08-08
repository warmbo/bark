// static/js/shared-utils.js
/**
 * Shared utilities for all modules to reduce code duplication
 */

class BarkAPI {
    /**
     * Generic API request handler with error handling
     */
    static async request(url, options = {}) {
        try {
            const response = await fetch(url, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }
            
            return data;
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    }

    /**
     * Load servers for any module
     */
    static async loadServers(moduleName) {
        return this.request(`/api/${moduleName}/get_servers`);
    }

    /**
     * Load channels for a server
     */
    static async loadChannels(moduleName, serverId) {
        return this.request(`/api/${moduleName}/get_channels?server_id=${serverId}`);
    }
}

class UIHelpers {
    /**
     * Show loading state for an element
     */
    static showLoading(element, message = 'Loading...') {
        if (typeof element === 'string') {
            element = document.getElementById(element);
        }
        
        element.textContent = message;
        element.className = 'api-result loading';
    }

    /**
     * Show error state for an element
     */
    static showError(element, error) {
        if (typeof element === 'string') {
            element = document.getElementById(element);
        }
        
        element.textContent = error;
        element.className = 'api-result error';
    }

    /**
     * Show success state for an element
     */
    static showSuccess(element, message) {
        if (typeof element === 'string') {
            element = document.getElementById(element);
        }
        
        element.textContent = message;
        element.className = 'api-result success';
    }

    /**
     * Populate a select element with options
     */
    static populateSelect(selectId, options, defaultText = 'Select an option') {
        const select = document.getElementById(selectId);
        if (!select) return;

        select.innerHTML = `<option value="">${defaultText}</option>`;
        
        options.forEach(option => {
            const optionEl = document.createElement('option');
            optionEl.value = option.id || option.value;
            optionEl.textContent = option.name || option.text || option.label;
            select.appendChild(optionEl);
        });
    }

    /**
     * Show notification toast
     */
    static showNotification(message, type = 'info') {
        // Create notification if it doesn't exist
        let notification = document.getElementById('notification');
        if (!notification) {
            notification = document.createElement('div');
            notification.id = 'notification';
            notification.className = 'notification';
            document.body.appendChild(notification);
        }

        notification.textContent = message;
        notification.className = `notification ${type} show`;

        // Auto-hide after 3 seconds
        setTimeout(() => {
            notification.classList.remove('show');
        }, 3000);
    }
}

class ModuleHelpers {
    /**
     * Generic server and channel loader for modules
     */
    static async setupServerChannelSelectors(moduleName, serverSelectId, channelSelectId) {
        try {
            // Load servers
            const serversData = await BarkAPI.loadServers(moduleName);
            UIHelpers.populateSelect(serverSelectId, serversData.servers, 'Select server');

            // Set up server change handler
            const serverSelect = document.getElementById(serverSelectId);
            const channelSelect = document.getElementById(channelSelectId);

            if (serverSelect && channelSelect) {
                serverSelect.addEventListener('change', async (e) => {
                    const serverId = e.target.value;
                    channelSelect.innerHTML = '<option value="">Select server first</option>';
                    channelSelect.disabled = true;

                    if (serverId) {
                        try {
                            UIHelpers.showLoading(channelSelect, 'Loading channels...');
                            const channelsData = await BarkAPI.loadChannels(moduleName, serverId);
                            UIHelpers.populateSelect(channelSelectId, 
                                channelsData.channels.map(ch => ({
                                    id: ch.id,
                                    name: `#${ch.name}`
                                })), 
                                'Select channel'
                            );
                            channelSelect.disabled = false;
                            channelSelect.className = '';
                        } catch (error) {
                            UIHelpers.showError(channelSelect, 'Failed to load channels');
                        }
                    }
                });
            }
        } catch (error) {
            console.error('Failed to setup server/channel selectors:', error);
            UIHelpers.showNotification('Failed to load servers', 'error');
        }
    }

    /**
     * Initialize module when it becomes active
     */
    static onModuleActivated(moduleId, initFunction) {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.target.id === moduleId && 
                    mutation.target.classList.contains('active')) {
                    initFunction();
                }
            });
        });

        const moduleElement = document.getElementById(moduleId);
        if (moduleElement) {
            observer.observe(moduleElement, {
                attributes: true,
                attributeFilter: ['class']
            });
        }
    }
}

// Add notification styles to the page
if (!document.getElementById('notification-styles')) {
    const style = document.createElement('style');
    style.id = 'notification-styles';
    style.textContent = `
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            color: white;
            font-weight: 500;
            z-index: 10000;
            transform: translateX(100%);
            transition: transform 0.3s ease;
            max-width: 400px;
        }
        
        .notification.show {
            transform: translateX(0);
        }
        
        .notification.info {
            background: var(--primary);
        }
        
        .notification.success {
            background: #10b981;
        }
        
        .notification.error {
            background: #ef4444;
        }
        
        .notification.warning {
            background: #f59e0b;
        }
    `;
    document.head.appendChild(style);
}