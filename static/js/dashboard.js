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
    
    document.getElementById('page-title').textContent = titles[moduleId] || 'Module';
    currentModule = moduleId;
    
    // Initialize module if needed
    if (moduleId === 'speak_as_bot') {
        loadServers();
    } else if (moduleId === 'server_stats') {
        loadStatsServers();
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

// Theme
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
                container.innerHTML = `
                    <h3>${data.stats.server.name}</h3>
                    <p>Members: ${data.stats.members.total}</p>
                    <p>Channels: ${data.stats.channels.total}</p>
                    <p>Created: ${data.stats.server.age_days} days ago</p>
                `;
            }
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}