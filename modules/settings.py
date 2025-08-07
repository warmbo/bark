import discord
from discord.ext import commands
from flask import jsonify, request
import json
import os

class SettingsModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Settings"
        self.description = "Configure dashboard appearance and manage modules"
        self.icon = "settings"
        self.version = "1.0.0"
        self.commands = []
        self.html = self.get_html()
        
        # Default settings
        self.default_settings = {
            "theme": {
                "primary_color": "#3b82f6",
                "font_family": "Inter"
            },
            "modules": {}
        }
        
        # Load saved settings
        self.settings_file = "dashboard_settings.json"
        self.load_settings()
    
    def load_settings(self):
        """Load settings from file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    self.settings = json.load(f)
            else:
                self.settings = self.default_settings.copy()
        except Exception as e:
            print(f"Error loading settings: {e}")
            self.settings = self.default_settings.copy()
    
    def save_settings(self):
        """Save settings to file"""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False
    
    def get_html(self):
        """Return the HTML for this module's interface"""
        return '''
        <div class="module-header">
            <h2><i data-lucide="settings"></i> Dashboard Settings</h2>
            <p>Customize your dashboard appearance and manage modules.</p>
        </div>
        
        <div class="settings-container">
            <!-- Theme Settings -->
            <div class="settings-section">
                <h3><i data-lucide="palette"></i> Theme Settings</h3>
                
                <div class="setting-group">
                    <label for="primary-color">Primary Color</label>
                    <div class="color-input-group">
                        <input type="color" id="primary-color" value="#3b82f6">
                        <input type="text" id="primary-color-hex" value="#3b82f6" placeholder="#3b82f6">
                    </div>
                    <small>Changes buttons, highlights, and accent colors</small>
                </div>
                
                <div class="setting-group">
                    <label for="font-family">Font Family</label>
                    <select id="font-family">
                        <option value="Inter">Inter (Default)</option>
                        <option value="system-ui">System UI</option>
                        <option value="Segoe UI">Segoe UI</option>
                        <option value="Roboto">Roboto</option>
                        <option value="Arial">Arial</option>
                        <option value="Helvetica">Helvetica</option>
                        <option value="Fira Code">Fira Code (Monospace)</option>
                        <option value="JetBrains Mono">JetBrains Mono</option>
                        <option value="Courier New">Courier New</option>
                    </select>
                    <small>Choose your preferred font for the dashboard</small>
                </div>
                
                <div class="setting-actions">
                    <button class="btn btn-primary" onclick="applyThemeSettings()">
                        <i data-lucide="check"></i>
                        Apply Theme
                    </button>
                    <button class="btn btn-secondary" onclick="resetThemeSettings()">
                        <i data-lucide="rotate-ccw"></i>
                        Reset to Default
                    </button>
                </div>
            </div>
            
            <!-- Module Management -->
            <div class="settings-section">
                <h3><i data-lucide="puzzle"></i> Module Management</h3>
                
                <div class="module-list" id="module-list">
                    <div class="loading-state">
                        <i data-lucide="loader"></i>
                        Loading modules...
                    </div>
                </div>
                
                <div class="setting-actions">
                    <button class="btn btn-primary" onclick="refreshModules()">
                        <i data-lucide="refresh-cw"></i>
                        Refresh Modules
                    </button>
                </div>
            </div>
            
            <!-- Advanced Settings -->
            <div class="settings-section">
                <h3><i data-lucide="sliders"></i> Advanced Settings</h3>
                
                <div class="setting-group">
                    <label>
                        <input type="checkbox" id="auto-save">
                        Auto-save settings
                    </label>
                    <small>Automatically save changes as you make them</small>
                </div>
                
                <div class="setting-group">
                    <label>
                        <input type="checkbox" id="compact-mode">
                        Compact mode
                    </label>
                    <small>Reduce padding and spacing for more content</small>
                </div>
                
                <div class="setting-actions">
                    <button class="btn btn-success" onclick="saveAllSettings()">
                        <i data-lucide="save"></i>
                        Save All Settings
                    </button>
                    <button class="btn btn-danger" onclick="exportSettings()">
                        <i data-lucide="download"></i>
                        Export Settings
                    </button>
                </div>
            </div>
        </div>
        
        <style>
        .settings-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 2rem;
        }
        
        .settings-section {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 0;
            padding: 2rem;
            backdrop-filter: var(--blur);
            -webkit-backdrop-filter: var(--blur);
        }
        
        .settings-section h3 {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 1.5rem;
            color: var(--text);
            font-size: 1.2rem;
            font-weight: 500;
        }
        
        .setting-group {
            margin-bottom: 1.5rem;
        }
        
        .setting-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--text);
            font-weight: 500;
        }
        
        .setting-group small {
            display: block;
            margin-top: 0.25rem;
            color: var(--text-muted);
            font-size: 0.8rem;
        }
        
        .color-input-group {
            display: flex;
            gap: 0.5rem;
            align-items: center;
        }
        
        .color-input-group input[type="color"] {
            width: 60px;
            height: 40px;
            border: none;
            border-radius: 0;
            cursor: pointer;
        }
        
        .color-input-group input[type="text"] {
            flex: 1;
            font-family: monospace;
        }
        
        .slider-group {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .slider-group input[type="range"] {
            flex: 1;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 0;
        }
        
        .slider-group span {
            min-width: 40px;
            color: var(--primary);
            font-weight: 500;
        }
        
        .setting-actions {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-top: 1.5rem;
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1rem;
            border: 1px solid transparent;
            border-radius: 0;
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            text-decoration: none;
        }
        
        .btn-primary {
            background: var(--primary);
            color: white;
            border-color: var(--primary);
        }
        
        .btn-primary:hover {
            opacity: 0.9;
        }
        
        .btn-secondary {
            background: var(--surface);
            color: var(--text);
            border-color: var(--border);
        }
        
        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.1);
        }
        
        .btn-success {
            background: #10b981;
            color: white;
            border-color: #10b981;
        }
        
        .btn-success:hover {
            opacity: 0.9;
        }
        
        .btn-danger {
            background: #ef4444;
            color: white;
            border-color: #ef4444;
        }
        
        .btn-danger:hover {
            opacity: 0.9;
        }
        
        .module-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 0;
            margin-bottom: 0.5rem;
        }
        
        .module-info {
            flex: 1;
        }
        
        .module-info h4 {
            margin: 0 0 0.25rem 0;
            color: var(--text);
        }
        
        .module-info p {
            margin: 0;
            color: var(--text-muted);
            font-size: 0.8rem;
        }
        
        .module-toggle {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .toggle-switch {
            position: relative;
            width: 50px;
            height: 25px;
            background: var(--border);
            border-radius: 0;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .toggle-switch.active {
            background: var(--primary);
        }
        
        .toggle-switch::before {
            content: "";
            position: absolute;
            top: 2px;
            left: 2px;
            width: 21px;
            height: 21px;
            background: white;
            border-radius: 0;
            transition: transform 0.2s;
        }
        
        .toggle-switch.active::before {
            transform: translateX(25px);
        }
        
        .loading-state {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 2rem;
            color: var(--text-muted);
            justify-content: center;
        }
        
        .loading-state i {
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        /* Checkbox styling */
        input[type="checkbox"] {
            width: 18px;
            height: 18px;
            margin-right: 0.5rem;
            accent-color: var(--primary);
        }
        
        /* Responsive adjustments */
        @media (max-width: 768px) {
            .settings-container {
                grid-template-columns: 1fr;
            }
            
            .setting-actions {
                flex-direction: column;
            }
            
            .btn {
                justify-content: center;
            }
        }
        </style>
        
        <script>
        // Load settings on module activation
        document.addEventListener('DOMContentLoaded', function() {
            loadCurrentSettings();
            loadModules();
            setupEventListeners();
        });
        
        function setupEventListeners() {
            // Color picker sync
            const colorPicker = document.getElementById('primary-color');
            const colorHex = document.getElementById('primary-color-hex');
            
            if (colorPicker && colorHex) {
                colorPicker.addEventListener('input', function() {
                    colorHex.value = this.value;
                });
                
                colorHex.addEventListener('input', function() {
                    if (this.value.match(/^#[0-9A-Fa-f]{6}$/)) {
                        colorPicker.value = this.value;
                    }
                });
            }
        }
        
        async function loadCurrentSettings() {
            try {
                const response = await fetch('/api/settings/get_settings');
                const data = await response.json();
                
                if (data.settings) {
                    const settings = data.settings;
                    
                    // Apply theme settings to form
                    if (settings.theme) {
                        const colorPicker = document.getElementById('primary-color');
                        const colorHex = document.getElementById('primary-color-hex');
                        const fontSelect = document.getElementById('font-family');
                        
                        if (colorPicker && settings.theme.primary_color) {
                            colorPicker.value = settings.theme.primary_color;
                            colorHex.value = settings.theme.primary_color;
                        }
                        
                        if (fontSelect && settings.theme.font_family) {
                            fontSelect.value = settings.theme.font_family;
                        }
                    }
                }
            } catch (error) {
                console.error('Failed to load settings:', error);
            }
        }
        
        async function loadModules() {
            try {
                const response = await fetch('/api/settings/get_modules');
                const data = await response.json();
                
                const moduleList = document.getElementById('module-list');
                if (data.modules) {
                    let html = '';
                    
                    for (const [moduleName, moduleData] of Object.entries(data.modules)) {
                        const isEnabled = moduleData.enabled !== false;
                        html += `
                            <div class="module-item">
                                <div class="module-info">
                                    <h4>${moduleData.name || moduleName}</h4>
                                    <p>${moduleData.description || 'No description available'}</p>
                                </div>
                                <div class="module-toggle">
                                    <div class="toggle-switch ${isEnabled ? 'active' : ''}" 
                                         onclick="toggleModule('${moduleName}', this)">
                                    </div>
                                </div>
                            </div>
                        `;
                    }
                    
                    moduleList.innerHTML = html;
                } else {
                    moduleList.innerHTML = '<div class="loading-state">No modules found</div>';
                }
            } catch (error) {
                console.error('Failed to load modules:', error);
                document.getElementById('module-list').innerHTML = 
                    '<div class="loading-state">Error loading modules</div>';
            }
        }
        
        async function toggleModule(moduleName, toggleElement) {
            const isEnabled = toggleElement.classList.contains('active');
            const newState = !isEnabled;
            
            try {
                const response = await fetch('/api/settings/toggle_module', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        module_name: moduleName,
                        enabled: newState
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    toggleElement.classList.toggle('active', newState);
                    
                    // Show feedback
                    const action = newState ? 'enabled' : 'disabled';
                    showNotification(`Module "${moduleName}" ${action}`, 'success');
                } else {
                    showNotification(`Failed to toggle module: ${data.error}`, 'error');
                }
            } catch (error) {
                console.error('Error toggling module:', error);
                showNotification('Error toggling module', 'error');
            }
        }
        
        function applyThemeSettings() {
            const primaryColor = document.getElementById('primary-color').value;
            const fontFamily = document.getElementById('font-family').value;
            
            // Apply to CSS variables
            document.documentElement.style.setProperty('--primary', primaryColor);
            document.body.style.fontFamily = fontFamily;
            
            // Save settings
            saveThemeSettings(primaryColor, fontFamily);
            
            showNotification('Theme applied successfully!', 'success');
        }
        
        async function saveThemeSettings(primaryColor, fontFamily) {
            try {
                await fetch('/api/settings/save_theme', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        primary_color: primaryColor,
                        font_family: fontFamily
                    })
                });
            } catch (error) {
                console.error('Error saving theme settings:', error);
            }
        }
        
        function resetThemeSettings() {
            document.getElementById('primary-color').value = '#3b82f6';
            document.getElementById('primary-color-hex').value = '#3b82f6';
            document.getElementById('font-family').value = 'Inter';
            
            applyThemeSettings();
        }
        
        async function refreshModules() {
            document.getElementById('module-list').innerHTML = 
                '<div class="loading-state"><i data-lucide="loader"></i> Loading modules...</div>';
            
            // Re-initialize Lucide icons
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
            
            await loadModules();
        }
        
        async function saveAllSettings() {
            try {
                const response = await fetch('/api/settings/save_all');
                const data = await response.json();
                
                if (data.success) {
                    showNotification('All settings saved successfully!', 'success');
                } else {
                    showNotification('Error saving settings', 'error');
                }
            } catch (error) {
                console.error('Error saving settings:', error);
                showNotification('Error saving settings', 'error');
            }
        }
        
        async function exportSettings() {
            try {
                const response = await fetch('/api/settings/export');
                const data = await response.json();
                
                if (data.settings) {
                    const blob = new Blob([JSON.stringify(data.settings, null, 2)], 
                        { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'bark-dashboard-settings.json';
                    a.click();
                    
                    URL.revokeObjectURL(url);
                    showNotification('Settings exported successfully!', 'success');
                } else {
                    showNotification('Error exporting settings', 'error');
                }
            } catch (error) {
                console.error('Error exporting settings:', error);
                showNotification('Error exporting settings', 'error');
            }
        }
        
        function showNotification(message, type) {
            // Simple notification system
            const notification = document.createElement('div');
            notification.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                padding: 1rem 1.5rem;
                background: ${type === 'success' ? '#10b981' : '#ef4444'};
                color: white;
                border-radius: 0;
                z-index: 10000;
                transition: all 0.3s ease;
            `;
            notification.textContent = message;
            
            document.body.appendChild(notification);
            
            setTimeout(() => {
                notification.style.opacity = '0';
                setTimeout(() => {
                    document.body.removeChild(notification);
                }, 300);
            }, 3000);
        }
        </script>
        '''
    
    def handle_api(self, action, request):
        """Handle API requests for this module"""
        if action == "get_settings":
            return jsonify({"settings": self.settings})
        
        elif action == "save_theme":
            data = request.get_json()
            if not self.settings.get("theme"):
                self.settings["theme"] = {}
            
            self.settings["theme"]["primary_color"] = data.get("primary_color", "#3b82f6")
            self.settings["theme"]["font_family"] = data.get("font_family", "Inter")
            
            success = self.save_settings()
            return jsonify({"success": success})
        
        elif action == "get_modules":
            # Get module information from module manager
            module_manager = getattr(self.bot, 'module_manager', None)
            modules_info = {}
            
            if module_manager:
                # Get loaded modules
                for name, instance in module_manager.loaded_modules.items():
                    modules_info[name] = {
                        "name": getattr(instance, 'name', name),
                        "description": getattr(instance, 'description', 'No description'),
                        "version": getattr(instance, 'version', '1.0.0'),
                        "enabled": True
                    }
                
                # Get module configs (enabled/disabled state)
                if hasattr(module_manager, 'module_configs'):
                    for name, config in module_manager.module_configs.items():
                        if name not in modules_info:
                            modules_info[name] = {
                                "name": name,
                                "description": "Module not loaded",
                                "version": config.get('version', '1.0.0'),
                                "enabled": config.get('enabled', False)
                            }
                        else:
                            modules_info[name]["enabled"] = config.get('enabled', True)
            
            return jsonify({"modules": modules_info})
        
        elif action == "toggle_module":
            data = request.get_json()
            module_name = data.get('module_name')
            enabled = data.get('enabled', True)
            
            module_manager = getattr(self.bot, 'module_manager', None)
            if not module_manager:
                return jsonify({"success": False, "error": "Module manager not available"}), 500
            
            try:
                if enabled:
                    success = module_manager.enable_module(module_name)
                else:
                    success = module_manager.disable_module(module_name)
                
                return jsonify({"success": success})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500
        
        elif action == "save_all":
            success = self.save_settings()
            return jsonify({"success": success})
        
        elif action == "export":
            return jsonify({"settings": self.settings})
        
        return jsonify({"error": "Unknown action"}), 404
    
    def cleanup(self):
        """Clean up when module is unloaded"""
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return SettingsModule(bot, app)