# base_module.py
"""
Base module class that provides common functionality and structure for all Bark modules.
This standardizes the module interface and reduces code duplication.
"""

import discord
from discord.ext import commands
from flask import jsonify
import asyncio
from typing import Dict, Any, Optional, List
import traceback

class BaseModule:
    """
    Base class for all Bark modules providing common functionality and structure.
    """
    
    def __init__(self, bot, app, module_manager=None):
        self.bot = bot
        self.app = app
        self.module_manager = module_manager
        
        # Module metadata - should be overridden in subclasses
        self.name = "Base Module"
        self.description = "Base module class"
        self.icon = "puzzle"
        self.version = "1.0.0"
        self.commands = []
        
        # System module flag - prevents toggling in settings
        self.is_system_module = False
        
        # HTML content for web interface
        self.html = self.get_html()
        
        # Register commands if defined
        self._register_commands()
    
    def _register_commands(self):
        """
        Override this method to register Discord commands.
        Use the @self.command() decorator or manually add commands.
        """
        pass
    
    def command(self, name: str = None, **kwargs):
        """
        Decorator for registering commands with automatic cleanup tracking.
        """
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
        """
        Standard error handling for commands.
        """
        error_embed = discord.Embed(
            title="❌ Command Error",
            description=f"An error occurred: {str(error)}",
            color=discord.Color.red()
        )
        
        if ctx and hasattr(ctx, 'send'):
            try:
                await ctx.send(embed=error_embed)
            except:
                pass  # Channel might not allow embeds
        
        print(f"Command error in {self.name}: {error}")
        print(traceback.format_exc())
    
    def get_html(self) -> str:
        """
        Return HTML content for the web dashboard.
        Override this method to provide custom interface.
        """
        return f'''
        <div class="module-header">
            <h2><i data-lucide="{self.icon}"></i> {self.name}</h2>
            <p>{self.description}</p>
        </div>
        
        <div class="module-content">
            <div class="info-section">
                <h3>📋 Commands</h3>
                <div class="command-list">
                    {self._generate_command_html()}
                </div>
            </div>
        </div>
        '''
    
    def _generate_command_html(self) -> str:
        """
        Generate HTML for command list based on registered commands.
        """
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
    
    def handle_api(self, action: str, request) -> tuple:
        """
        Handle API requests for this module.
        Override this method to add custom API endpoints.
        
        Args:
            action: The API action requested
            request: Flask request object
            
        Returns:
            Tuple of (response_data, status_code) or just response_data
        """
        if action == "get_info":
            return jsonify({
                "name": self.name,
                "description": self.description,
                "version": self.version,
                "commands": self.commands
            })
        
        return jsonify({"error": "Unknown action"}), 404
    
    def run_async_in_bot_loop(self, coro, timeout: float = 10):
        """
        Helper method to run async operations in the bot's event loop from sync contexts.
        
        Args:
            coro: Coroutine to run
            timeout: Timeout in seconds
            
        Returns:
            Result of the coroutine
        """
        if not hasattr(self.bot, 'loop') or not self.bot.loop.is_running():
            raise RuntimeError("Bot event loop is not available")
        
        future = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
        return future.result(timeout=timeout)
    
    def create_embed(self, title: str, description: str = None, 
                    color: discord.Color = discord.Color.blue(), **kwargs) -> discord.Embed:
        """
        Helper method to create standardized embeds.
        """
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
    
    def validate_permissions(self, ctx, permission: str) -> bool:
        """
        Helper method to validate user permissions.
        """
        if not hasattr(ctx.author, 'guild_permissions'):
            return False
        
        return getattr(ctx.author.guild_permissions, permission, False)
    
    def get_storage(self):
        """
        Get access to the storage system if available.
        """
        if hasattr(self.bot, 'storage'):
            return self.bot.storage
        return None
    
    def log_event(self, server_id: str, event_type: str, data: Dict = None):
        """
        Log an event to the storage system if available.
        """
        storage = self.get_storage()
        if storage:
            try:
                storage.log_event(server_id, f"{self.name.lower()}_{event_type}", data)
            except Exception as e:
                print(f"Failed to log event: {e}")
    
    def get_module_data(self, server_id: str, key: str, default=None):
        """
        Get module-specific data from storage.
        """
        storage = self.get_storage()
        if storage:
            try:
                return storage.get_module_data(self.name.lower(), server_id, key, default)
            except Exception as e:
                print(f"Failed to get module data: {e}")
        return default
    
    def set_module_data(self, server_id: str, key: str, value):
        """
        Set module-specific data in storage.
        """
        storage = self.get_storage()
        if storage:
            try:
                return storage.set_module_data(self.name.lower(), server_id, key, value)
            except Exception as e:
                print(f"Failed to set module data: {e}")
                return False
        return False
    
    def cleanup(self):
        """
        Clean up module resources when unloading.
        Override to add custom cleanup logic.
        """
        # Remove registered commands
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")
    
    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name} v{self.version}>"