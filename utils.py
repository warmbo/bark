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
import time
import json
from typing import Dict, Any, Optional, List, Callable


class APIHelpers:
    """Centralized utilities for module API handling"""
    
    @staticmethod
    def handle_bot_async(bot, coro, timeout=10):
        """Safely run async Discord operations from Flask threads"""
        if not hasattr(bot, 'loop') or not bot.loop.is_running():
            raise RuntimeError("Bot not ready")
        
        try:
            future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
            return future.result(timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"Operation timed out after {timeout} seconds")
        except Exception as e:
            raise RuntimeError(f"Bot operation failed: {str(e)}")
    
    @staticmethod
    def standard_error_response(error_msg: str, status_code: int = 400, error_code: str = None) -> tuple:
        """Standardized error response format"""
        response = {
            "error": error_msg,
            "success": False,
            "timestamp": int(time.time())
        }
        if error_code:
            response["error_code"] = error_code
        return jsonify(response), status_code
    
    @staticmethod
    def standard_success_response(data: Optional[Dict[str, Any]] = None, message: str = None) -> tuple:
        """Standardized success response format"""
        response = {
            "success": True,
            "timestamp": int(time.time())
        }
        if message:
            response["message"] = message
        if data:
            response.update(data)
        return jsonify(response)
    
    @staticmethod
    def require_bot_ready(func: Callable) -> Callable:
        """Decorator to ensure bot is ready before API calls"""
        @wraps(func)
        def wrapper(self, action, request_obj):
            if not hasattr(self.bot, 'is_ready') or not self.bot.is_ready():
                return APIHelpers.standard_error_response("Bot is not ready", 503, "BOT_NOT_READY")
            return func(self, action, request_obj)
        return wrapper
    
    @staticmethod
    def validate_json_params(required_params: list = None, optional_params: list = None):
        """Decorator to validate required JSON parameters"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(self, action, request_obj, *args, **kwargs):
                try:
                    data = request_obj.get_json()
                    if not data:
                        return APIHelpers.standard_error_response("No JSON data provided", 400, "MISSING_JSON")
                    
                    # Check required parameters
                    if required_params:
                        missing = [param for param in required_params if param not in data]
                        if missing:
                            return APIHelpers.standard_error_response(
                                f"Missing required parameters: {', '.join(missing)}", 400, "MISSING_PARAMS"
                            )
                    
                    # Filter to only allowed parameters
                    allowed_params = (required_params or []) + (optional_params or [])
                    if allowed_params:
                        filtered_data = {k: v for k, v in data.items() if k in allowed_params}
                    else:
                        filtered_data = data
                    
                    return func(self, action, request_obj, filtered_data, *args, **kwargs)
                    
                except json.JSONDecodeError:
                    return APIHelpers.standard_error_response("Invalid JSON format", 400, "INVALID_JSON")
                except Exception as e:
                    return APIHelpers.standard_error_response(f"Request validation error: {str(e)}", 500, "VALIDATION_ERROR")
            return wrapper
        return decorator


class DiscordHelpers:
    """Discord-specific helper functions"""
    
    @staticmethod
    async def get_server_channels(bot, server_id: str, text_only: bool = True, include_categories: bool = False):
        """Get channels for a server with enhanced filtering options"""
        try:
            guild = bot.get_guild(int(server_id))
            if not guild:
                return None
            
            channels = []
            
            # Get the appropriate channel list
            if text_only:
                channel_list = guild.text_channels
            else:
                channel_list = [ch for ch in guild.channels if hasattr(ch, 'send')]
            
            # Add categories if requested
            if include_categories:
                for category in guild.categories:
                    channels.append({
                        "id": str(category.id),
                        "name": category.name,
                        "type": "category",
                        "position": category.position
                    })
            
            # Add channels
            for channel in channel_list:
                if hasattr(channel, 'permissions_for'):
                    permissions = channel.permissions_for(guild.me)
                    if not permissions.send_messages:
                        continue
                
                channel_data = {
                    "id": str(channel.id),
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": getattr(channel, 'position', 0)
                }
                
                # Add category info if available
                if hasattr(channel, 'category') and channel.category:
                    channel_data["category"] = channel.category.name
                    channel_data["category_id"] = str(channel.category.id)
                
                channels.append(channel_data)
            
            # Sort by position
            channels.sort(key=lambda x: x.get('position', 0))
            return channels
            
        except (ValueError, Exception) as e:
            print(f"Error getting channels for server {server_id}: {e}")
            return None
    
    @staticmethod
    async def get_server_list(bot, include_stats: bool = False):
        """Get list of all servers with optional statistics"""
        servers = []
        
        for guild in bot.guilds:
            server_data = {
                "id": str(guild.id),
                "name": guild.name
            }
            
            if include_stats:
                server_data.update({
                    "member_count": guild.member_count,
                    "owner_id": str(guild.owner_id) if guild.owner_id else None,
                    "icon_url": str(guild.icon.url) if guild.icon else None,
                    "boost_level": guild.premium_tier,
                    "boost_count": guild.premium_subscription_count
                })
            
            servers.append(server_data)
        
        servers.sort(key=lambda x: x['name'].lower())
        return servers
    
    @staticmethod
    async def get_server_stats(bot, server_id: str):
        """Get comprehensive server statistics"""
        try:
            guild = bot.get_guild(int(server_id))
            if not guild:
                return None
            
            # Count members by status
            online = sum(1 for member in guild.members if member.status != discord.Status.offline)
            bots = sum(1 for member in guild.members if member.bot)
            humans = guild.member_count - bots
            
            # Count channels by type
            text_channels = len(guild.text_channels)
            voice_channels = len(guild.voice_channels)
            categories = len(guild.categories)
            
            return {
                "server": {
                    "id": str(guild.id),
                    "name": guild.name,
                    "owner": str(guild.owner) if guild.owner else "Unknown",
                    "owner_id": str(guild.owner_id) if guild.owner_id else None,
                    "created_at": guild.created_at.isoformat(),
                    "member_limit": guild.max_members,
                    "description": guild.description,
                    "verification_level": str(guild.verification_level),
                    "icon_url": str(guild.icon.url) if guild.icon else None
                },
                "members": {
                    "total": guild.member_count,
                    "humans": humans,
                    "bots": bots,
                    "online": online
                },
                "channels": {
                    "text": text_channels,
                    "voice": voice_channels,
                    "categories": categories,
                    "total": text_channels + voice_channels
                },
                "boosts": {
                    "level": guild.premium_tier,
                    "count": guild.premium_subscription_count
                },
                "features": list(guild.features),
                "roles": len(guild.roles)
            }
            
        except (ValueError, Exception) as e:
            print(f"Error getting stats for server {server_id}: {e}")
            return None
    
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
        if not hasattr(self, 'is_system_module'):
            self.is_system_module = False
        if not hasattr(self, 'dependencies'):
            self.dependencies = []
        
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
                pass
        
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
        return getattr(self.bot, 'storage', None)
    
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

.api-result.loading {{ color: var(--text-muted); }}
.api-result.error {{ color: #ef4444; }}
.api-result.success {{ color: #10b981; }}
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