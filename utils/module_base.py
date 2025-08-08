# utils/module_base.py
import discord
from discord.ext import commands
from flask import jsonify
from abc import ABC, abstractmethod

class BaseModule(ABC):
    """Base class for all Bark modules to ensure consistency"""
    
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.commands = []  # Track commands for cleanup
        
        # These should be set by subclasses
        self.name = "Base Module"
        self.description = "Base module description"
        self.icon = "puzzle"
        self.version = "1.0.0"
        
        # Optional attributes
        self.is_system_module = False
        self.dependencies = []  # Other modules this depends on
        
        # Initialize the module
        self._register_commands()
        self.html = self.get_html()
    
    @abstractmethod
    def _register_commands(self):
        """Register Discord commands - must be implemented by subclasses"""
        pass
    
    @abstractmethod
    def get_html(self):
        """Return HTML for web interface - must be implemented by subclasses"""
        pass
    
    def handle_api(self, action, request):
        """Handle API requests - can be overridden by subclasses"""
        return jsonify({"error": "No API endpoints defined"}), 404
    
    def cleanup(self):
        """Clean up when module is unloaded"""
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")
    
    def get_module_info(self):
        """Get standardized module information"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "icon": self.icon,
            "is_system": self.is_system_module,
            "dependencies": self.dependencies,
            "commands": self.commands
        }
    
    def check_dependencies(self, loaded_modules):
        """Check if all dependencies are loaded"""
        missing = [dep for dep in self.dependencies if dep not in loaded_modules]
        return len(missing) == 0, missing
    
    def create_embed(self, title, description=None, color=discord.Color.blue(), **fields):
        """Helper to create consistent embeds"""
        embed = discord.Embed(title=title, description=description, color=color)
        
        for name, value in fields.items():
            inline = isinstance(value, tuple) and len(value) == 2
            if inline:
                embed.add_field(name=name, value=value[0], inline=value[1])
            else:
                embed.add_field(name=name, value=value, inline=False)
        
        return embed

# Standard HTML template for modules
MODULE_HTML_TEMPLATE = '''
<div class="module-header">
    <h2><i data-lucide="{icon}"></i> {name}</h2>
    <p>{description}</p>
</div>

<div class="{module_id}-container">
    {content}
</div>

<style>
.{module_id}-container {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 1.5rem;
}}

.info-section, .test-section, .config-section {{
    background: var(--glass-bg);
    backdrop-filter: var(--blur);
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    padding: 1.5rem;
}}

.section-title {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1rem;
    color: var(--text);
}}

.command-list {{
    display: flex;
    flex-direction: column;
    gap: 1rem;
}}

.command-item {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
}}

.command-item code {{
    background: var(--background);
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-family: 'Courier New', monospace;
    color: var(--primary);
    font-weight: bold;
}}

.api-result {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    margin-top: 1rem;
    min-height: 60px;
    color: var(--text);
}}

.api-result.loading {{
    color: var(--text-muted);
}}

.api-result.error {{
    color: #ef4444;
}}

.api-result.success {{
    color: #10b981;
}}
</style>
'''

def format_module_html(module_id, name, description, icon, content):
    """Helper function to format module HTML consistently"""
    return MODULE_HTML_TEMPLATE.format(
        module_id=module_id.replace('_', '-'),
        name=name,
        description=description,
        icon=icon,
        content=content
    )