# modules/settings.py
from flask import jsonify, request

class SettingsModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Settings"
        self.description = "Bot configuration and module management"
        self.icon = "settings"
        self.version = "1.0.0"
        self.commands = []
        
        # Special attribute to indicate this is a system module
        self.is_system_module = True
        
        self.html = self.get_html()
    
    def get_html(self):
        """Return the HTML for the settings interface"""
        return '''
        <div class="module-header">
            <h2><i data-lucide="settings"></i> Settings</h2>
            <p>Configure bot settings and manage modules.</p>
        </div>
        
        <div class="settings-container">
            <div class="theme-section">
                <h3><i data-lucide="palette"></i> Theme</h3>
                <div class="form-group">
                    <label for="primary-color">Primary Color</label>
                    <input type="color" id="primary-color" value="#3b82f6">
                </div>
                <button class="btn btn-primary" onclick="saveTheme()">
                    <i data-lucide="save"></i>
                    Save Theme
                </button>
            </div>
            
            <div class="module-management-section">
                <h3><i data-lucide="puzzle"></i> Module Management</h3>
                <div id="module-list" class="module-toggle-list">
                    Loading modules...
                </div>
                <button class="btn btn-secondary" onclick="refreshModules()">
                    <i data-lucide="refresh-cw"></i>
                    Refresh
                </button>
            </div>
            
            <div class="bot-info-section">
                <h3><i data-lucide="info"></i> Bot Information</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <span class="info-label">Bot Prefix</span>
                        <span class="info-value" id="bot-prefix">Loading...</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Web Port</span>
                        <span class="info-value" id="web-port">Loading...</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Modules Directory</span>
                        <span class="info-value">modules/</span>
                    </div>
                </div>
            </div>
        </div>
        
        <style>
        .settings-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
        }
        
        .theme-section, .module-management-section, .bot-info-section {
            background: var(--glass-bg);
            backdrop-filter: var(--blur);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 1.5rem;
        }
        
        .theme-section h3, .module-management-section h3, .bot-info-section h3 {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 1rem;
            color: var(--text);
        }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--text);
            font-weight: 500;
        }
        
        .form-group input {
            width: 100%;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.75rem;
            color: var(--text);
            font-family: inherit;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0.75rem 1rem;
            cursor: pointer;
            transition: all 0.2s;
            font-family: inherit;
            font-weight: 500;
        }
        
        .btn:hover {
            opacity: 0.9;
            transform: translateY(-1px);
        }
        
        .btn-secondary {
            background: var(--surface);
            color: var(--text);
            border: 1px solid var(--border);
        }
        
        .module-toggle-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            margin-bottom: 1rem;
        }
        
        .module-toggle-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
        }
        
        .module-info {
            flex: 1;
        }
        
        .module-name {
            font-weight: 500;
            color: var(--text);
            margin-bottom: 0.25rem;
        }
        
        .module-desc {
            font-size: 0.9rem;
            color: var(--text-muted);
        }
        
        .module-toggle {
            position: relative;
            width: 44px;
            height: 24px;
            background: var(--border);
            border-radius: 12px;
            cursor: pointer;
            transition: background-color 0.2s;
        }
        
        .module-toggle.enabled {
            background: var(--primary);
        }
        
        .module-toggle::after {
            content: '';
            position: absolute;
            top: 2px;
            left: 2px;
            width: 20px;
            height: 20px;
            background: white;
            border-radius: 50%;
            transition: transform 0.2s;
        }
        
        .module-toggle.enabled::after {
            transform: translateX(20px);
        }
        
        .info-grid {
            display: grid;
            gap: 1rem;
        }
        
        .info-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
        }
        
        .info-label {
            font-weight: 500;
            color: var(--text);
        }
        
        .info-value {
            color: var(--text-muted);
            font-family: 'Courier New', monospace;
        }
        </style>
        
        <script>
        // Load saved theme on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadSavedTheme();
            loadModuleList();
            loadBotInfo();
            
            // Initialize Lucide icons
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        });
        
        function loadSavedTheme() {
            const saved = localStorage.getItem('theme-primary');
            if (saved) {
                document.documentElement.style.setProperty('--primary', saved);
                const input = document.getElementById('primary-color');
                if (input) input.value = saved;
            }
        }
        
        function saveTheme() {
            const primary = document.getElementById('primary-color').value;
            document.documentElement.style.setProperty('--primary', primary);
            localStorage.setItem('theme-primary', primary);
            
            // Show success feedback
            const button = event.target;
            const originalText = button.innerHTML;
            button.innerHTML = '<i data-lucide="check"></i> Saved!';
            setTimeout(() => {
                button.innerHTML = originalText;
                lucide.createIcons();
            }, 2000);
            
            lucide.createIcons();
        }
        
        async function loadModuleList() {
            try {
                const response = await fetch('/api/settings/get_modules');
                if (response.ok) {
                    const data = await response.json();
                    displayModules(data.modules);
                }
            } catch (error) {
                console.error('Failed to load modules:', error);
                document.getElementById('module-list').innerHTML = 
                    '<div style="color: #ef4444;">Failed to load modules</div>';
            }
        }
        
        function displayModules(modules) {
            const container = document.getElementById('module-list');
            container.innerHTML = '';
            
            Object.entries(modules).forEach(([name, info]) => {
                // Skip system modules from the toggle list
                if (info.is_system_module) return;
                
                const item = document.createElement('div');
                item.className = 'module-toggle-item';
                item.innerHTML = `
                    <div class="module-info">
                        <div class="module-name">${info.name || name}</div>
                        <div class="module-desc">${info.description || 'No description'}</div>
                    </div>
                    <div class="module-toggle ${info.enabled ? 'enabled' : ''}" 
                         onclick="toggleModule('${name}', ${info.enabled})">
                    </div>
                `;
                container.appendChild(item);
            });
            
            if (container.children.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted);">No modules found</div>';
            }
        }
        
        async function toggleModule(moduleName, currentState) {
            const action = currentState ? 'disable' : 'enable';
            
            try {
                const response = await fetch(`/api/settings/toggle_module`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ module: moduleName, action: action })
                });
                
                if (response.ok) {
                    // Refresh the module list
                    loadModuleList();
                } else {
                    alert('Failed to toggle module');
                }
            } catch (error) {
                console.error('Error toggling module:', error);
                alert('Error toggling module');
            }
        }
        
        function refreshModules() {
            loadModuleList();
            
            // Show refresh feedback
            const button = event.target;
            const originalText = button.innerHTML;
            button.innerHTML = '<i data-lucide="loader-2"></i> Refreshing...';
            button.style.pointerEvents = 'none';
            
            setTimeout(() => {
                button.innerHTML = originalText;
                button.style.pointerEvents = 'auto';
                lucide.createIcons();
            }, 1000);
            
            lucide.createIcons();
        }
        
        async function loadBotInfo() {
            try {
                const response = await fetch('/api/settings/get_bot_info');
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('bot-prefix').textContent = data.prefix || '!';
                    document.getElementById('web-port').textContent = data.port || '5000';
                }
            } catch (error) {
                console.error('Failed to load bot info:', error);
            }
        }
        </script>
        '''
    
    def handle_api(self, action, request):
        """Handle API requests for settings"""
        if action == "get_modules":
            # Get module info but mark system modules
            module_info = self.bot.module_manager.get_module_info()
            
            # Combine loaded and available modules
            all_modules = {}
            
            # Add loaded modules
            for name, info in module_info['loaded'].items():
                module_instance = self.bot.module_manager.loaded_modules.get(name)
                all_modules[name] = {
                    **info,
                    'loaded': True,
                    'is_system_module': getattr(module_instance, 'is_system_module', False)
                }
            
            # Add available but not loaded modules
            for name, info in module_info['available'].items():
                all_modules[name] = {
                    **info,
                    'is_system_module': False  # Unloaded modules can't be system modules
                }
            
            return jsonify({"modules": all_modules})
        
        elif action == "toggle_module":
            data = request.get_json()
            module_name = data.get('module')
            action_type = data.get('action')
            
            if not module_name or action_type not in ['enable', 'disable']:
                return jsonify({"error": "Invalid request"}), 400
            
            # Don't allow toggling system modules
            if module_name in self.bot.module_manager.loaded_modules:
                module_instance = self.bot.module_manager.loaded_modules[module_name]
                if getattr(module_instance, 'is_system_module', False):
                    return jsonify({"error": "Cannot toggle system modules"}), 403
            
            try:
                if action_type == 'enable':
                    success = self.bot.module_manager.enable_module(module_name)
                else:
                    success = self.bot.module_manager.disable_module(module_name)
                
                return jsonify({"success": success})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        elif action == "get_bot_info":
            import os
            return jsonify({
                "prefix": os.getenv('BOT_PREFIX', '!'),
                "port": os.getenv('WEB_PORT', '5000')
            })
        
        return jsonify({"error": "Unknown action"}), 404
    
    def cleanup(self):
        """No cleanup needed for settings module"""
        pass

def setup(bot, app):
    return SettingsModule(bot, app)