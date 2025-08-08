# utils.py - Consolidated utilities for Bark Discord Bot
"""
Consolidated utility functions and classes for the Bark Discord bot.
Combines module base classes, API helpers, and Discord utilities.
"""

import discord
from discord.ext import commands
from flask import jsonify, request
import asyncio
from functools import wraps
from abc import ABC, abstractmethod
import traceback
from typing import Dict, Any, Optional, List


class APIHelpers:
    """Centralized utilities for module API handling"""
    
    @staticmethod
    def handle_bot_async(bot, coro, timeout=10):
        """Safely run async Discord operations from Flask threads"""
        if not hasattr(bot, 'loop') or not bot.loop.is_running():
            raise RuntimeError("Bot not ready")
        
        future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        return future.result(timeout=timeout)
    
    @staticmethod
    def standard_error_response(error_msg, status_code=400):
        """Standardized error response format"""
        return jsonify({"error": error_msg, "success": False}), status_code
    
    @staticmethod
    def standard_success_response(data=None):
        """Standardized success response format"""
        response = {"success": True}
        if data:
            response.update(data)
        return jsonify(response)
    
    @staticmethod
    def require_bot_ready(func):
        """Decorator to ensure bot is ready before API calls"""
        @wraps(func)
        def wrapper(self, action, request):
            if not hasattr(self.bot, 'loop') or not self.bot.loop.is_running():
                return APIHelpers.standard_error_response("Bot not ready", 503)
            return func(self, action, request)
        return wrapper
    
    @staticmethod
    def validate_json_params(required_params):
        """Decorator to validate required JSON parameters"""
        def decorator(func):
            @wraps(func)
            def wrapper(self, action, request):
                data = request.get_json()
                if not data:
                    return APIHelpers.standard_error_response("No JSON data provided")
                
                missing = [param for param in required_params if param not in data]
                if missing:
                    return APIHelpers.standard_error_response(f"Missing parameters: {', '.join(missing)}")
                
                return func(self, action, request, data)
            return wrapper
        return decorator


class DiscordHelpers:
    """Discord-specific helper functions"""
    
    @staticmethod
    async def get_server_channels(bot, server_id, text_only=True):
        """Get channels for a server"""
        guild = bot.get_guild(int(server_id))
        if not guild:
            return None
        
        channels = []
        channel_list = guild.text_channels if text_only else guild.channels
        
        for channel in channel_list:
            if hasattr(channel, 'permissions_for') and channel.permissions_for(guild.me).send_messages:
                channels.append({
                    "id": str(channel.id),
                    "name": channel.name,
                    "type": str(channel.type)
                })
        
        return channels
    
    @staticmethod
    async def get_server_list(bot):
        """Get list of all servers"""
        return [
            {"id": str(guild.id), "name": guild.name}
            for guild in bot.guilds
        ]
    
    @staticmethod
    def create_embed(title: str, description: str = None, 
                    color: discord.Color = discord.Color.blue(), **kwargs) -> discord.Embed:
        """Helper to create standardized embeds"""
        embed = discord.Embed(title=title, description=description, color=color)
        
        for key, value in kwargs.items():
            if key.startswith('field_'):
                # Handle fields like field_name_value_inline
                parts = key.split('_')
                if len(parts) >= 3:
                    field_name = parts[1]
                    field_value = value
                    inline = parts[-1] == 'inline' if len(parts) > 2 else False
                    embed.add_field(name=field_name, value=field_value, inline=inline)
            elif hasattr(embed, f'set_{key}'):
                getattr(embed, f'set_{key}')(value)
        
        return embed


class BaseModule(ABC):
    """Base class for all Bark modules providing common functionality and structure."""
    
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.commands = []  # Track commands for cleanup
        
        # Set defaults only if not already set by subclass
        if not hasattr(self, 'name'):
            self.name = "Base Module"
        if not hasattr(self, 'description'):
            self.description = "Base module description"
        if not hasattr(self, 'icon'):
            self.icon = "puzzle"
        if not hasattr(self, 'version'):
            self.version = "1.0.0"
        
        # Optional attributes - set defaults only if not already set
        if not hasattr(self, 'is_system_module'):
            self.is_system_module = False
        if not hasattr(self, 'dependencies'):
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
    
    def command(self, name: str = None, **kwargs):
        """Decorator for registering commands with automatic cleanup tracking."""
        def decorator(func):
            cmd_name = name or func.__name__
            
            @self.bot.command(name=cmd_name, **kwargs)
            async def wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    await self._handle_command_error(args[0] if args else None, e)
            
            # Track command for cleanup
            if cmd_name not in self.commands:
                self.commands.append(cmd_name)
            
            return wrapper
        return decorator
    
    async def _handle_command_error(self, ctx, error):
        """Standard error handling for commands."""
        error_embed = DiscordHelpers.create_embed(
            "❌ Command Error",
            f"An error occurred: {str(error)}",
            discord.Color.red()
        )
        
        if ctx and hasattr(ctx, 'send'):
            try:
                await ctx.send(embed=error_embed)
            except:
                pass  # Channel might not allow embeds
        
        print(f"Command error in {self.name}: {error}")
        print(traceback.format_exc())
    
    def handle_api(self, action: str, request) -> tuple:
        """Handle API requests for this module."""
        if action == "get_info":
            return APIHelpers.standard_success_response({
                "name": self.name,
                "description": self.description,
                "version": self.version,
                "commands": self.commands
            })
        
        return APIHelpers.standard_error_response("Unknown action", 404)
    
    def run_async_in_bot_loop(self, coro, timeout: float = 10):
        """Helper method to run async operations in the bot's event loop from sync contexts."""
        return APIHelpers.handle_bot_async(self.bot, coro, timeout)
    
    def create_embed(self, title: str, description: str = None, 
                    color: discord.Color = discord.Color.blue(), **kwargs) -> discord.Embed:
        """Helper method to create standardized embeds."""
        return DiscordHelpers.create_embed(title, description, color, **kwargs)
    
    def validate_permissions(self, ctx, permission: str) -> bool:
        """Helper method to validate user permissions."""
        if not hasattr(ctx.author, 'guild_permissions'):
            return False
        
        return getattr(ctx.author.guild_permissions, permission, False)
    
    def get_storage(self):
        """Get access to the storage system if available."""
        if hasattr(self.bot, 'storage'):
            return self.bot.storage
        return None
    
    def log_event(self, server_id: str, event_type: str, data: Dict = None):
        """Log an event to the storage system if available."""
        storage = self.get_storage()
        if storage:
            try:
                storage.log_event(server_id, f"{self.name.lower()}_{event_type}", data)
            except Exception as e:
                print(f"Failed to log event: {e}")
    
    def get_module_data(self, server_id: str, key: str, default=None):
        """Get module-specific data from storage."""
        storage = self.get_storage()
        if storage:
            try:
                return storage.get_module_data(self.name.lower(), server_id, key, default)
            except Exception as e:
                print(f"Failed to get module data: {e}")
        return default
    
    def set_module_data(self, server_id: str, key: str, value):
        """Set module-specific data in storage."""
        storage = self.get_storage()
        if storage:
            try:
                return storage.set_module_data(self.name.lower(), server_id, key, value)
            except Exception as e:
                print(f"Failed to set module data: {e}")
                return False
        return False
    
    def cleanup(self):
        """Clean up module resources when unloading."""
        # Remove registered commands
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")
    
    def _generate_command_html(self) -> str:
        """Generate HTML for command list based on registered commands."""
        if not self.commands:
            return '<p class="text-muted">No commands available</p>'
        
        html_parts = []
        for cmd_name in self.commands:
            cmd = self.bot.get_command(cmd_name)
            if cmd:
                help_text = cmd.help or "No description available"
                html_parts.append(f'''
                    <div class="command-item">
                        <code>bark-{cmd_name}</code>
                        <span>{help_text}</span>
                    </div>
                ''')
        
        return '\n'.join(html_parts)
    
    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name} v{self.version}>"


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