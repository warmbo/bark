// Dashboard functionality
class Dashboard {
    constructor() {
        this.currentModule = 'home';
        this.init();
    }

    init() {
        this.initLucideIcons();
        this.loadDashboardStats();
        this.setupThemeControls();
        this.loadSavedTheme();
    }

    initLucideIcons() {
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }

    showModule(moduleId) {
        // Hide all modules
        document.querySelectorAll('.module-content').forEach(el => {
            el.classList.remove('active');
        });

        // Remove active class from nav items
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.remove('active');
        });

        // Show selected module
        const moduleEl = document.getElementById(moduleId);
        if (moduleEl) {
            moduleEl.classList.add('active');
        }

        // Update nav item
        const navItem = document.querySelector(`[onclick="showModule('${moduleId}')"]`);
        if (navItem) {
            navItem.classList.add('active');
        }

        // Update page title
        const pageTitle = document.getElementById('page-title');
        if (pageTitle) {
            if (moduleId === 'home') {
                pageTitle.textContent = 'Dashboard';
            } else if (moduleId === 'settings') {
                pageTitle.textContent = 'Settings';
            } else {
                // Get module name from nav item
                const moduleNameEl = navItem?.querySelector('span');
                pageTitle.textContent = moduleNameEl?.textContent || 'Module';
            }
        }

        this.currentModule = moduleId;

        // Trigger module-specific initialization if needed
        this.initializeModule(moduleId);
    }

    initializeModule(moduleId) {
        switch (moduleId) {
            case 'speak_as_bot':
                this.initSpeakAsBotModule();
                break;
            case 'server_stats':
                this.initServerStatsModule();
                break;
        }
    }

    async loadDashboardStats() {
        try {
            // Load basic stats for the home dashboard
            const response = await fetch('/api/dashboard/stats');
            if (response.ok) {
                const data = await response.json();
                this.updateDashboardStats(data);
            }
        } catch (error) {
            console.error('Failed to load dashboard stats:', error);
        }
    }

    updateDashboardStats(stats) {
        const serverCount = document.getElementById('server-count');
        const memberCount = document.getElementById('member-count');
        const onlineCount = document.getElementById('online-count');

        if (serverCount) serverCount.textContent = stats.servers || '0';
        if (memberCount) memberCount.textContent = stats.members || '0';
        if (onlineCount) onlineCount.textContent = stats.online || '0';
    }

    // Theme Management
    setupThemeControls() {
        const colorInputs = document.querySelectorAll('input[type="color"]');
        colorInputs.forEach(input => {
            input.addEventListener('change', this.previewTheme.bind(this));
        });
    }

    previewTheme() {
        const primary = document.getElementById('primary-color')?.value;
        const accent = document.getElementById('accent-color')?.value;
        const background = document.getElementById('background-color')?.value;
        const surface = document.getElementById('surface-color')?.value;

        if (primary) document.documentElement.style.setProperty('--primary', primary);
        if (accent) document.documentElement.style.setProperty('--accent', accent);
        if (background) document.documentElement.style.setProperty('--background', background);
        if (surface) document.documentElement.style.setProperty('--surface', surface);
    }

    async saveTheme() {
        const theme = {
            primary: document.getElementById('primary-color')?.value,
            accent: document.getElementById('accent-color')?.value,
            background: document.getElementById('background-color')?.value,
            surface: document.getElementById('surface-color')?.value
        };

        try {
            const response = await fetch('/api/theme', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(theme)
            });

            if (response.ok) {
                localStorage.setItem('dashboard-theme', JSON.stringify(theme));
                this.showNotification('Theme saved successfully!', 'success');
            }
        } catch (error) {
            this.showNotification('Failed to save theme', 'error');
        }
    }

    resetTheme() {
        const defaultTheme = {
            primary: '#3b82f6',
            accent: '#06b6d4',
            background: '#0f172a',
            surface: '#1e293b'
        };

        // Update inputs
        Object.entries(defaultTheme).forEach(([key, value]) => {
            const input = document.getElementById(`${key}-color`);
            if (input) input.value = value;
        });

        // Apply theme
        Object.entries(defaultTheme).forEach(([key, value]) => {
            document.documentElement.style.setProperty(`--${key}`, value);
        });

        localStorage.removeItem('dashboard-theme');
        this.showNotification('Theme reset to default', 'success');
    }

    loadSavedTheme() {
        const savedTheme = localStorage.getItem('dashboard-theme');
        if (savedTheme) {
            try {
                const theme = JSON.parse(savedTheme);
                Object.entries(theme).forEach(([key, value]) => {
                    document.documentElement.style.setProperty(`--${key}`, value);
                    const input = document.getElementById(`${key}-color`);
                    if (input) input.value = value;
                });
            } catch (error) {
                console.error('Failed to load saved theme:', error);
            }
        }
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `status-message status-${type}`;
        notification.textContent = message;
        notification.style.position = 'fixed';
        notification.style.top = '20px';
        notification.style.right = '20px';
        notification.style.zIndex = '1000';
        notification.style.animation = 'fadeIn 0.3s ease';

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'fadeOut 0.3s ease';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }

    // Module-specific initialization
    async initSpeakAsBotModule() {
        try {
            const response = await fetch('/api/speak_as_bot/get_servers');
            if (response.ok) {
                const data = await response.json();
                this.populateServerSelect('server-select', data.servers);
            }
        } catch (error) {
            console.error('Failed to load servers for speak as bot module:', error);
        }
    }

    async initServerStatsModule() {
        try {
            const response = await fetch('/api/server_stats/get_servers');
            if (response.ok) {
                const data = await response.json();
                this.populateServerSelect('stats-server-select', data.servers);
            }
        } catch (error) {
            console.error('Failed to load servers for stats module:', error);
        }
    }

    populateServerSelect(selectId, servers) {
        const select = document.getElementById(selectId);
        if (!select) return;

        select.innerHTML = '<option value="">Select a server</option>';
        servers.forEach(server => {
            const option = document.createElement('option');
            option.value = server.id;
            option.textContent = server.name;
            select.appendChild(option);
        });
    }

    // Utility methods for modules
    async sendMessage(channelId, message) {
        try {
            const response = await fetch('/api/speak_as_bot/send_message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: channelId, message })
            });
            
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('Failed to send message:', error);
            return { success: false, error: error.message };
        }
    }

    async loadChannels(serverId, selectId) {
        try {
            const response = await fetch(`/api/speak_as_bot/get_channels?server_id=${serverId}`);
            if (response.ok) {
                const data = await response.json();
                const select = document.getElementById(selectId);
                if (select) {
                    select.innerHTML = '<option value="">Select a channel</option>';
                    data.channels.forEach(channel => {
                        const option = document.createElement('option');
                        option.value = channel.id;
                        option.textContent = '#' + channel.name;
                        select.appendChild(option);
                    });
                    select.disabled = false;
                }
            }
        } catch (error) {
            console.error('Failed to load channels:', error);
        }
    }
}

// Global dashboard instance
const dashboard = new Dashboard();

// Global functions for HTML onclick handlers
function showModule(moduleId) {
    dashboard.showModule(moduleId);
}

function toggleTheme() {
    // Could implement theme toggle between light/dark modes
    dashboard.showModule('settings');
}

function saveTheme() {
    dashboard.saveTheme();
}

function resetTheme() {
    dashboard.resetTheme();
}

// Speak as Bot Module Functions
function loadServers() {
    dashboard.initSpeakAsBotModule();
}

function loadChannels(serverId) {
    dashboard.loadChannels(serverId, 'channel-select');
}

async function sendMessage() {
    const channelId = document.getElementById('channel-select')?.value;
    const message = document.getElementById('message-input')?.value;
    const statusDiv = document.getElementById('status-message');

    if (!channelId || !message) {
        dashboard.showNotification('Please select a channel and enter a message.', 'error');
        return;
    }

    const result = await dashboard.sendMessage(channelId, message);
    
    if (result.success) {
        dashboard.showNotification('Message sent successfully!', 'success');
        document.getElementById('message-input').value = '';
    } else {
        dashboard.showNotification('Error: ' + result.error, 'error');
    }
}

// Server Stats Module Functions
function loadStatsServers() {
    dashboard.initServerStatsModule();
}

async function loadServerStats() {
    const serverId = document.getElementById('stats-server-select')?.value;
    if (!serverId) {
        document.getElementById('stats-container').style.display = 'none';
        return;
    }

    try {
        const response = await fetch(`/api/server_stats/get_stats?server_id=${serverId}`);
        const data = await response.json();
        
        if (data.error) {
            dashboard.showNotification(data.error, 'error');
            return;
        }

        displayStats(data.stats);
        loadChannelsForStats(serverId);
    } catch (error) {
        dashboard.showNotification('Failed to load server stats', 'error');
    }
}

function displayStats(stats) {
    document.getElementById('stats-container').style.display = 'block';
    document.getElementById('server-name').textContent = stats.server.name;

    // Update stats display
    const memberStats = document.getElementById('member-stats');
    if (memberStats) {
        memberStats.innerHTML = `
            <p>Total Members: <strong>${stats.members.total}</strong></p>
            <p>Humans: <strong>${stats.members.humans}</strong></p>
            <p>Bots: <strong>${stats.members.bots}</strong></p>
            <p>Online: <strong>${stats.members.online}</strong></p>
        `;
    }

    const channelStats = document.getElementById('channel-stats');
    if (channelStats) {
        channelStats.innerHTML = `
            <p>Text Channels: <strong>${stats.channels.text}</strong></p>
            <p>Voice Channels: <strong>${stats.channels.voice}</strong></p>
            <p>Categories: <strong>${stats.channels.categories}</strong></p>
            <p>Total: <strong>${stats.channels.total}</strong></p>
        `;
    }

    const serverInfo = document.getElementById('server-info');
    if (serverInfo) {
        serverInfo.innerHTML = `
            <p>Owner: <strong>${stats.server.owner}</strong></p>
            <p>Created: <strong>${stats.server.age_days}</strong> days ago</p>
            <p>Roles: <strong>${stats.roles}</strong></p>
            <p>Boosts: <strong>${stats.boosts.count}</strong> (Level ${stats.boosts.level})</p>
        `;
    }
}

function loadChannelsForStats(serverId) {
    dashboard.loadChannels(serverId, 'stats-channel-select');
}

async function sendStatsToChannel() {
    const serverId = document.getElementById('stats-server-select')?.value;
    const channelId = document.getElementById('stats-channel-select')?.value;

    if (!channelId) {
        dashboard.showNotification('Please select a channel', 'error');
        return;
    }

    try {
        const response = await fetch('/api/server_stats/send_stats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server_id: serverId, channel_id: channelId })
        });

        const data = await response.json();
        
        if (data.success) {
            dashboard.showNotification('Stats sent successfully!', 'success');
        } else {
            dashboard.showNotification('Error: ' + data.error, 'error');
        }
    } catch (error) {
        dashboard.showNotification('Failed to send stats', 'error');
    }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    dashboard.init();
});