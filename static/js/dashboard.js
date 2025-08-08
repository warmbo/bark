// Simple Dashboard
let currentModule = 'home';

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadDashboardStats();
    loadSavedTheme();
});

// Module Navigation
function showModule(moduleId) {
    // Hide all modules
    document.querySelectorAll('.module').forEach(el => {
        el.classList.remove('active');
    });
    
    // Remove active from nav items
    document.querySelectorAll('.nav-item').forEach(el => {
        el.classList.remove('active');
    });
    
    // Show selected module
    const moduleEl = document.getElementById(moduleId);
    if (moduleEl) {
        moduleEl.classList.add('active');
    }
    
    // Update nav
    const navItem = document.querySelector(`[onclick="showModule('${moduleId}')"]`);
    if (navItem) {
        navItem.classList.add('active');
    }
    
    // Update title
    const titles = {
        home: 'Dashboard',
        about: 'About',
        settings: 'Settings'
    };
    
    // Get module name from nav item or use default
    let displayTitle = titles[moduleId];
    if (!displayTitle && navItem) {
        displayTitle = navItem.textContent.trim();
    } else if (!displayTitle) {
        displayTitle = 'Module';
    }
    
    document.getElementById('page-title').textContent = displayTitle;
    currentModule = moduleId;
    
    // Initialize module if needed
    if (moduleId === 'speak_as_bot') {
        loadServers();
    } else if (moduleId === 'server_stats') {
        loadStatsServers();
    }
    
    // Reinitialize Lucide icons for dynamic content
    if (typeof lucide !== 'undefined') {
        setTimeout(() => {
            lucide.createIcons();
        }, 100);
    }
}

// Dashboard Stats
async function loadDashboardStats() {
    try {
        const response = await fetch('/api/dashboard/stats');
        if (response.ok) {
            const data = await response.json();
            document.getElementById('server-count').textContent = data.servers || '0';
            document.getElementById('member-count').textContent = data.members || '0';
            document.getElementById('online-count').textContent = data.online || '0';
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

// Theme (moved from settings, now global utility)
function saveTheme() {
    const primary = document.getElementById('primary-color').value;
    document.documentElement.style.setProperty('--primary', primary);
    localStorage.setItem('theme-primary', primary);
    alert('Theme saved!');
}

function loadSavedTheme() {
    const saved = localStorage.getItem('theme-primary');
    if (saved) {
        document.documentElement.style.setProperty('--primary', saved);
        const input = document.getElementById('primary-color');
        if (input) input.value = saved;
    }
}

// Speak as Bot Module
async function loadServers() {
    try {
        const response = await fetch('/api/speak_as_bot/get_servers');
        if (response.ok) {
            const data = await response.json();
            const select = document.getElementById('server-select');
            if (select) {
                select.innerHTML = '<option value="">Select server</option>';
                data.servers.forEach(server => {
                    const option = document.createElement('option');
                    option.value = server.id;
                    option.textContent = server.name;
                    select.appendChild(option);
                });
            }
        }
    } catch (error) {
        console.error('Failed to load servers:', error);
    }
}

async function loadChannels(serverId) {
    try {
        const response = await fetch(`/api/speak_as_bot/get_channels?server_id=${serverId}`);
        if (response.ok) {
            const data = await response.json();
            const select = document.getElementById('channel-select');
            if (select) {
                select.innerHTML = '<option value="">Select channel</option>';
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

async function sendMessage() {
    const channelId = document.getElementById('channel-select')?.value;
    const message = document.getElementById('message-input')?.value;
    
    if (!channelId || !message) {
        alert('Please select a channel and enter a message');
        return;
    }
    
    try {
        const response = await fetch('/api/speak_as_bot/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: channelId, message })
        });
        
        const data = await response.json();
        if (data.success) {
            alert('Message sent!');
            document.getElementById('message-input').value = '';
        } else {
            alert('Error: ' + data.error);
        }
    } catch (error) {
        alert('Failed to send message');
    }
}

// Server Stats Module
async function loadStatsServers() {
    try {
        const response = await fetch('/api/server_stats/get_servers');
        if (response.ok) {
            const data = await response.json();
            const select = document.getElementById('stats-server-select');
            if (select) {
                select.innerHTML = '<option value="">Select server</option>';
                data.servers.forEach(server => {
                    const option = document.createElement('option');
                    option.value = server.id;
                    option.textContent = server.name;
                    select.appendChild(option);
                });
            }
        }
    } catch (error) {
        console.error('Failed to load servers:', error);
    }
}

async function loadServerStats() {
    const serverId = document.getElementById('stats-server-select')?.value;
    if (!serverId) return;
    
    try {
        const response = await fetch(`/api/server_stats/get_stats?server_id=${serverId}`);
        const data = await response.json();
        
        if (data.stats) {
            const container = document.getElementById('stats-container');
            if (container) {
                container.style.display = 'block';
                
                // Update server name
                const nameEl = document.getElementById('server-name');
                if (nameEl) {
                    nameEl.textContent = data.stats.server.name;
                }
                
                // Update member stats
                const memberStatsEl = document.getElementById('member-stats');
                if (memberStatsEl) {
                    memberStatsEl.innerHTML = `
                        <p>Total: <strong>${data.stats.members.total}</strong></p>
                        <p>Humans: <strong>${data.stats.members.humans}</strong></p>
                        <p>Bots: <strong>${data.stats.members.bots}</strong></p>
                        <p>Online: <strong>${data.stats.members.online}</strong></p>
                    `;
                }
                
                // Update channel stats
                const channelStatsEl = document.getElementById('channel-stats');
                if (channelStatsEl) {
                    channelStatsEl.innerHTML = `
                        <p>Text: <strong>${data.stats.channels.text}</strong></p>
                        <p>Voice: <strong>${data.stats.channels.voice}</strong></p>
                        <p>Categories: <strong>${data.stats.channels.categories}</strong></p>
                        <p>Total: <strong>${data.stats.channels.total}</strong></p>
                    `;
                }
                
                // Update server info
                const serverInfoEl = document.getElementById('server-info');
                if (serverInfoEl) {
                    serverInfoEl.innerHTML = `
                        <p>Owner: <strong>${data.stats.server.owner}</strong></p>
                        <p>Created: <strong>${data.stats.server.age_days} days ago</strong></p>
                        <p>Roles: <strong>${data.stats.roles}</strong></p>
                        <p>Boosts: <strong>${data.stats.boosts.count} (Level ${data.stats.boosts.level})</strong></p>
                    `;
                }
                
                // Load channels for stats sending
                loadStatsChannels(serverId);
            }
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

async function loadStatsChannels(serverId) {
    try {
        const response = await fetch(`/api/server_stats/get_channels?server_id=${serverId}`);
        if (response.ok) {
            const data = await response.json();
            const select = document.getElementById('stats-channel-select');
            if (select) {
                select.innerHTML = '<option value="">Select a channel</option>';
                data.channels.forEach(channel => {
                    const option = document.createElement('option');
                    option.value = channel.id;
                    option.textContent = '#' + channel.name;
                    select.appendChild(option);
                });
            }
        }
    } catch (error) {
        console.error('Failed to load channels for stats:', error);
    }
}

async function sendStatsToChannel() {
    const serverId = document.getElementById('stats-server-select')?.value;
    const channelId = document.getElementById('stats-channel-select')?.value;
    
    if (!serverId || !channelId) {
        alert('Please select a server and channel');
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
            alert('Stats sent to channel!');
        } else {
            alert('Error: ' + (data.error || 'Failed to send stats'));
        }
    } catch (error) {
        alert('Failed to send stats to channel');
        console.error('Error:', error);
    }
}