# system_modules/settings.py
from flask import jsonify, request
import os
import sys
import importlib.util

# Import utils from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import BaseModule, APIHelpers, format_module_html

class SettingsModule(BaseModule):
    def __init__(self, bot, app):
        self.name = "Settings"
        self.description = "Bot configuration and module management"
        self.icon = "settings"
        self.version = "1.1.0"
        
        # Mark as system module to prevent disabling
        self.is_system_module = True
        self.dependencies = []
        
        super().__init__(bot, app)
    
    def _register_commands(self):
        """No Discord commands for settings module"""
        pass
    
    def get_html(self):
        """Return the HTML for the settings interface"""
        content = '''
        <div class="info-section">
            <h3 class="section-title">
                <i data-lucide="palette"></i> 
                Theme Customization
            </h3>
            <div class="theme-controls">
                <div class="form-group">
                    <label for="primary-color">Primary Color</label>
                    <div class="color-input-group">
                        <input type="color" id="primary-color" value="#3b82f6">
                        <input type="text" id="primary-color-text" value="#3b82f6" placeholder="#3b82f6">
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="theme-preset">Theme Presets</label>
                    <select id="theme-preset" onchange="applyThemePreset()">
                        <option value="custom">Custom</option>
                        <option value="blue">Ocean Blue</option>
                        <option value="green">Forest Green</option>
                        <option value="purple">Royal Purple</option>
                        <option value="red">Crimson Red</option>
                        <option value="orange">Sunset Orange</option>
                    </select>
                </div>
                
                <button class="btn btn-primary" onclick="saveTheme()">
                    <i data-lucide="save"></i>
                    Save Theme
                </button>
                <button class="btn btn-secondary" onclick="resetTheme()">
                    <i data-lucide="rotate-ccw"></i>
                    Reset to Default
                </button>
            </div>
        </div>
        
        <div class="info-section">
            <h3 class="section-title">
                <i data-lucide="puzzle"></i> 
                Module Management
            </h3>
            <div class="module-controls">
                <div class="controls-header">
                    <button class="btn btn-secondary" onclick="refreshModules()">
                        <i data-lucide="refresh-cw"></i>
                        Refresh
                    </button>
                    <button class="btn btn-secondary" onclick="reloadAllModules()">
                        <i data-lucide="rotate-cw"></i>
                        Reload All
                    </button>
                </div>
                
                <div id="module-list" class="module-toggle-list">
                    <div class="loading-placeholder">Loading modules...</div>
                </div>
            </div>
        </div>
        
        <div class="info-section">
            <h3 class="section-title">
                <i data-lucide="info"></i> 
                Bot Information
            </h3>
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
                <div class="info-item">
                    <span class="info-label">System Modules</span>
                    <span class="info-value">system_modules/</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Hot Reload</span>
                    <span class="info-value status-enabled">
                        <i data-lucide="check-circle"></i> Enabled
                    </span>
                </div>
            </div>
            
            <div class="system-actions">
                <button class="btn btn-secondary" onclick="viewLogs()">
                    <i data-lucide="file-text"></i>
                    View Logs
                </button>
                <button class="btn btn-secondary" onclick="exportConfig()">
                    <i data-lucide="download"></i>
                    Export Config
                </button>
            </div>
        </div>
        
        <!-- Logs Modal -->
        <div id="logs-modal" class="modal" style="display: none;">
            <div class="modal-content">
                <div class="modal-header">
                    <h4>System Logs</h4>
                    <button class="modal-close" onclick="closeLogs()">
                        <i data-lucide="x"></i>
                    </button>
                </div>
                <div class="modal-body">
                    <div id="logs-content" class="logs-container">
                        Loading logs...
                    </div>
                </div>
            </div>
        </div>
        
        <script>
        // Theme presets
        const themePresets = {
            blue: '#3b82f6',
            green: '#10b981',
            purple: '#8b5cf6',
            red: '#ef4444',
            orange: '#f97316'
        };
        
        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {
            if (document.getElementById('settings') && document.getElementById('settings').classList.contains('active')) {
                loadSavedTheme();
                loadModuleList();
                loadBotInfo();
                setupColorInputs();
                
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            }
        });
        
        // Also trigger when module becomes active
        function initializeSettings() {
            loadSavedTheme();
            loadModuleList();
            loadBotInfo();
            setupColorInputs();
            
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
        
        function setupColorInputs() {
            const colorInput = document.getElementById('primary-color');
            const textInput = document.getElementById('primary-color-text');
            
            if (colorInput && textInput) {
                colorInput.addEventListener('change', function() {
                    textInput.value = this.value;
                    document.getElementById('theme-preset').value = 'custom';
                });
                
                textInput.addEventListener('input', function() {
                    if (/^#[0-9A-F]{6}$/i.test(this.value)) {
                        colorInput.value = this.value;
                        document.getElementById('theme-preset').value = 'custom';
                    }
                });
            }
        }
        
        function loadSavedTheme() {
            const saved = localStorage.getItem('theme-primary');
            if (saved) {
                document.documentElement.style.setProperty('--primary', saved);
                const colorInput = document.getElementById('primary-color');
                const textInput = document.getElementById('primary-color-text');
                if (colorInput) colorInput.value = saved;
                if (textInput) textInput.value = saved;
            }
        }
        
        function applyThemePreset() {
            const preset = document.getElementById('theme-preset').value;
            if (preset !== 'custom' && themePresets[preset]) {
                const color = themePresets[preset];
                document.getElementById('primary-color').value = color;
                document.getElementById('primary-color-text').value = color;
            }
        }
        
        function saveTheme() {
            const primary = document.getElementById('primary-color').value;
            document.documentElement.style.setProperty('--primary', primary);
            localStorage.setItem('theme-primary', primary);
            
            showNotification('Theme saved successfully!', 'success');
            
            const button = document.querySelector('button[onclick="saveTheme()"]');
            if (button) {
                const originalText = button.innerHTML;
                button.innerHTML = '<i data-lucide="check"></i> Saved!';
                setTimeout(() => {
                    button.innerHTML = originalText;
                    if (typeof lucide !== 'undefined') {
                        lucide.createIcons();
                    }
                }, 2000);
            }
            
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
        
        function resetTheme() {
            const defaultColor = '#3b82f6';
            document.getElementById('primary-color').value = defaultColor;
            document.getElementById('primary-color-text').value = defaultColor;
            document.getElementById('theme-preset').value = 'blue';
            document.documentElement.style.setProperty('--primary', defaultColor);
            localStorage.setItem('theme-primary', defaultColor);
            
            showNotification('Theme reset to default', 'info');
        }
        
        async function loadModuleList() {
            try {
                const response = await fetch('/api/settings/get_modules');
                const data = await response.json();
                displayModules(data.modules);
            } catch (error) {
                console.error('Failed to load modules:', error);
                const container = document.getElementById('module-list');
                if (container) {
                    container.innerHTML = '<div class="error-placeholder">Failed to load modules: ' + error.message + '</div>';
                }
            }
        }
        
        function displayModules(modules) {
            const container = document.getElementById('module-list');
            if (!container) return;
            
            container.innerHTML = '';
            
            const moduleEntries = Object.entries(modules || {});
            
            // Separate system and regular modules
            const systemModules = moduleEntries.filter(([name, info]) => info.is_system_module);
            const regularModules = moduleEntries.filter(([name, info]) => !info.is_system_module);
            
            // Show system modules first (read-only)
            if (systemModules.length > 0) {
                const systemHeader = document.createElement('div');
                systemHeader.className = 'module-category-header';
                systemHeader.innerHTML = '<h4>System Modules</h4>';
                container.appendChild(systemHeader);
                
                systemModules.forEach(([name, info]) => {
                    container.appendChild(createModuleItem(name, info, true));
                });
            }
            
            // Show regular modules
            if (regularModules.length > 0) {
                const regularHeader = document.createElement('div');
                regularHeader.className = 'module-category-header';
                regularHeader.innerHTML = '<h4>Modules</h4>';
                container.appendChild(regularHeader);
                
                regularModules.forEach(([name, info]) => {
                    container.appendChild(createModuleItem(name, info, false));
                });
            }
            
            if (moduleEntries.length === 0) {
                container.innerHTML = '<div class="empty-placeholder">No modules found</div>';
            }
        }
        
        function createModuleItem(name, info, isSystem) {
            const item = document.createElement('div');
            item.className = 'module-toggle-item';
            
            const statusClass = info.loaded ? 'loaded' : 'unloaded';
            const deps = info.dependencies && info.dependencies.length > 0 
                ? `<div class="module-deps">Requires: ${info.dependencies.join(', ')}</div>` 
                : '';
            
            item.innerHTML = `
                <div class="module-info">
                    <div class="module-header-info">
                        <div class="module-name">${info.name || name}</div>
                        <div class="module-status ${statusClass}">
                            ${info.loaded ? 'Loaded' : 'Available'}
                        </div>
                    </div>
                    <div class="module-desc">${info.description || 'No description'}</div>
                    ${deps}
                </div>
                <div class="module-controls-section">
                    ${isSystem ? 
                        '<span class="system-badge">System</span>' :
                        `<div class="module-toggle ${info.enabled ? 'enabled' : ''}" 
                              onclick="toggleModule('${name}', ${info.enabled})">
                         </div>`
                    }
                </div>
            `;
            
            return item;
        }
        
        async function toggleModule(moduleName, currentState) {
            const action = currentState ? 'disable' : 'enable';
            
            try {
                const response = await fetch('/api/settings/toggle_module', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ module: moduleName, action: action })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showNotification(`Module ${moduleName} ${action}d successfully`, 'success');
                    loadModuleList();
                } else {
                    showNotification(`Failed to ${action} module: ${data.error}`, 'error');
                }
            } catch (error) {
                console.error('Error toggling module:', error);
                showNotification(`Failed to ${action} module: ${error.message}`, 'error');
            }
        }
        
        function refreshModules() {
            loadModuleList();
            showNotification('Module list refreshed', 'info');
        }
        
        async function reloadAllModules() {
            try {
                const response = await fetch('/api/settings/reload_all_modules', {
                    method: 'POST'
                });
                const data = await response.json();
                
                if (data.success) {
                    showNotification('All modules reloaded', 'success');
                    setTimeout(loadModuleList, 1000);
                } else {
                    showNotification(`Failed to reload modules: ${data.error}`, 'error');
                }
            } catch (error) {
                showNotification(`Failed to reload modules: ${error.message}`, 'error');
            }
        }
        
        async function loadBotInfo() {
            try {
                const response = await fetch('/api/settings/get_bot_info');
                const data = await response.json();
                
                const prefixEl = document.getElementById('bot-prefix');
                const portEl = document.getElementById('web-port');
                
                if (prefixEl) prefixEl.textContent = data.prefix || '!';
                if (portEl) portEl.textContent = data.port || '5000';
            } catch (error) {
                console.error('Failed to load bot info:', error);
            }
        }
        
        async function viewLogs() {
            const modal = document.getElementById('logs-modal');
            const content = document.getElementById('logs-content');
            
            if (modal && content) {
                modal.style.display = 'flex';
                content.textContent = 'Loading logs...';
                
                try {
                    const response = await fetch('/api/settings/get_logs');
                    const data = await response.json();
                    content.innerHTML = `<pre>${data.logs}</pre>`;
                } catch (error) {
                    content.textContent = 'Failed to load logs: ' + error.message;
                }
            }
        }
        
        function closeLogs() {
            const modal = document.getElementById('logs-modal');
            if (modal) {
                modal.style.display = 'none';
            }
        }
        
        async function exportConfig() {
            try {
                const response = await fetch('/api/settings/export_config');
                const data = await response.json();
                
                // Create download
                const blob = new Blob([JSON.stringify(data.config, null, 2)], 
                    { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                
                const a = document.createElement('a');
                a.href = url;
                a.download = `bark-config-${new Date().toISOString().split('T')[0]}.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                
                showNotification('Configuration exported', 'success');
            } catch (error) {
                showNotification('Failed to export config: ' + error.message, 'error');
            }
        }
        
        function showNotification(message, type) {
            console.log(`[${type.toUpperCase()}] ${message}`);
            // Simple notification - could be enhanced with toast notifications
        }
        
        // Close modal when clicking outside
        window.addEventListener('click', function(event) {
            const modal = document.getElementById('logs-modal');
            if (event.target === modal) {
                closeLogs();
            }
        });
        
        // Export initialization function for external use
        window.initializeSettings = initializeSettings;
        </script>
        '''
        
        return format_module_html('settings', self.name, self.description, self.icon, content)
    
    def handle_api(self, action, request):
        """Handle API requests for settings"""
        try:
            if action == "get_modules":
                # Get comprehensive module info including dependencies
                module_info = self.bot.module_manager.get_module_info()
                
                # Combine loaded and available modules with enhanced info
                all_modules = {}
                
                # Add loaded modules
                for name, info in module_info['loaded'].items():
                    module_instance = self.bot.module_manager.loaded_modules.get(name)
                    all_modules[name] = {
                        **info,
                        'loaded': True,
                        'is_system_module': getattr(module_instance, 'is_system_module', False),
                        'dependencies': getattr(module_instance, 'dependencies', [])
                    }
                
                # Add available but not loaded modules
                for name, info in module_info['available'].items():
                    if name not in all_modules:
                        all_modules[name] = {
                            **info,
                            'loaded': False,
                            'is_system_module': info.get('is_system_module', False)
                        }
                
                return APIHelpers.standard_success_response({"modules": all_modules})
            
            elif action == "toggle_module":
                data = request.get_json()
                if not data:
                    return APIHelpers.standard_error_response("No JSON data provided")
                
                module_name = data.get('module')
                action_type = data.get('action')
                
                if not module_name or action_type not in ['enable', 'disable']:
                    return APIHelpers.standard_error_response("Invalid request parameters")
                
                # Prevent toggling system modules
                if module_name in self.bot.module_manager.loaded_modules:
                    module_instance = self.bot.module_manager.loaded_modules[module_name]
                    if getattr(module_instance, 'is_system_module', False):
                        return APIHelpers.standard_error_response("Cannot toggle system modules", 403)
                
                try:
                    if action_type == 'enable':
                        success = self.bot.module_manager.enable_module(module_name)
                    else:
                        success = self.bot.module_manager.disable_module(module_name)
                    
                    if success:
                        return APIHelpers.standard_success_response({
                            "message": f"Module {module_name} {action_type}d successfully"
                        })
                    else:
                        return APIHelpers.standard_error_response(f"Failed to {action_type} module")
                        
                except Exception as e:
                    return APIHelpers.standard_error_response(str(e), 500)
            
            elif action == "reload_all_modules":
                try:
                    # Get list of currently loaded modules (excluding system modules)
                    modules_to_reload = []
                    for name, module_instance in self.bot.module_manager.loaded_modules.items():
                        if not getattr(module_instance, 'is_system_module', False):
                            modules_to_reload.append(name)
                    
                    # Reload each module
                    reloaded_count = 0
                    for module_name in modules_to_reload:
                        if self.bot.module_manager.reload_module(module_name):
                            reloaded_count += 1
                    
                    return APIHelpers.standard_success_response({
                        "message": f"Reloaded {reloaded_count}/{len(modules_to_reload)} modules"
                    })
                    
                except Exception as e:
                    return APIHelpers.standard_error_response(str(e), 500)
            
            elif action == "get_bot_info":
                return APIHelpers.standard_success_response({
                    "prefix": os.getenv('BOT_PREFIX', '!'),
                    "port": os.getenv('WEB_PORT', '5000'),
                    "modules_loaded": len(self.bot.module_manager.loaded_modules),
                    "hot_reload": True
                })
            
            elif action == "get_logs":
                # Return recent log entries (this would need to be implemented with actual logging)
                return APIHelpers.standard_success_response({
                    "logs": "Log viewing not yet implemented.\nThis would show recent bot activity and errors.\n\nConsole output should show module loading information and any errors."
                })
            
            elif action == "export_config":
                try:
                    config = {
                        "modules": self.bot.module_manager.module_configs,
                        "bot_settings": {
                            "prefix": os.getenv('BOT_PREFIX', '!'),
                            "port": os.getenv('WEB_PORT', '5000')
                        },
                        "export_date": __import__('datetime').datetime.now().isoformat()
                    }
                    return APIHelpers.standard_success_response({"config": config})
                except Exception as e:
                    return APIHelpers.standard_error_response(str(e), 500)
        
        except Exception as e:
            return APIHelpers.standard_error_response(f"Settings error: {str(e)}", 500)
        
        return APIHelpers.standard_error_response("Unknown action", 404)

def setup(bot, app):
    return SettingsModule(bot, app)