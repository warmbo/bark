# utils/api_helpers.py
import asyncio
import json
import time
from flask import jsonify, request
from functools import wraps
from typing import Dict, Any, Optional, Callable
import traceback

class APIHelpers:
    """Centralized utilities for module API handling with improved error handling and standardization"""
    
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
        """Standardized error response format with enhanced error information"""
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
        """Standardized success response format with optional message"""
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
    def validate_json_request(required_params: list = None, optional_params: list = None):
        """Decorator to validate JSON request parameters"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    data = request.get_json()
                    if not data:
                        return APIHelpers.standard_error_response(
                            "No JSON data provided", 
                            400, 
                            "MISSING_JSON"
                        )
                    
                    # Check required parameters
                    if required_params:
                        missing = [param for param in required_params if param not in data]
                        if missing:
                            return APIHelpers.standard_error_response(
                                f"Missing required parameters: {', '.join(missing)}", 
                                400, 
                                "MISSING_PARAMS"
                            )
                    
                    # Filter to only allowed parameters
                    allowed_params = (required_params or []) + (optional_params or [])
                    if allowed_params:
                        filtered_data = {k: v for k, v in data.items() if k in allowed_params}
                    else:
                        filtered_data = data
                    
                    # Add filtered data to kwargs
                    kwargs['validated_data'] = filtered_data
                    
                    return func(*args, **kwargs)
                    
                except json.JSONDecodeError:
                    return APIHelpers.standard_error_response(
                        "Invalid JSON format", 
                        400, 
                        "INVALID_JSON"
                    )
                except Exception as e:
                    return APIHelpers.standard_error_response(
                        f"Request validation error: {str(e)}", 
                        500, 
                        "VALIDATION_ERROR"
                    )
                    
            return wrapper
        return decorator
    
    @staticmethod
    def require_bot_ready(func: Callable) -> Callable:
        """Decorator to ensure bot is ready before API calls"""
        @wraps(func)
        def wrapper(self, action, request_obj):
            if not hasattr(self.bot, 'is_ready') or not self.bot.is_ready():
                return APIHelpers.standard_error_response(
                    "Bot is not ready", 
                    503, 
                    "BOT_NOT_READY"
                )
            return func(self, action, request_obj)
        return wrapper
    
    @staticmethod
    def log_api_request(func: Callable) -> Callable:
        """Decorator to log API requests for debugging"""
        @wraps(func)
        def wrapper(self, action, request_obj):
            module_name = getattr(self, 'name', 'unknown')
            
            # Log request
            print(f"[API] {module_name}/{action} - {request_obj.method}")
            
            try:
                result = func(self, action, request_obj)
                return result
            except Exception as e:
                print(f"[API ERROR] {module_name}/{action}: {str(e)}")
                print(traceback.format_exc())
                
                return APIHelpers.standard_error_response(
                    "Internal server error", 
                    500, 
                    "INTERNAL_ERROR"
                )
                
        return wrapper

class DiscordHelpers:
    """Discord-specific helper functions with enhanced error handling"""
    
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
                categories = guild.categories
                for category in categories:
                    channels.append({
                        "id": str(category.id),
                        "name": category.name,
                        "type": "category",
                        "position": category.position
                    })
            
            # Add channels
            for channel in channel_list:
                # Check bot permissions
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
            
        except ValueError:
            # Invalid server ID
            return None
        except Exception as e:
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
        
        # Sort by name
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
            online = sum(1 for member in guild.members if member.status != guild.members[0].status.offline)
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
            
        except ValueError:
            return None
        except Exception as e:
            print(f"Error getting stats for server {server_id}: {e}")
            return None

class ModuleRegistry:
    """Simple registry for tracking module metadata and dependencies"""
    
    _modules = {}
    _dependencies = {}
    
    @classmethod
    def register_module(cls, name: str, instance, dependencies: list = None):
        """Register a module with the registry"""
        cls._modules[name] = {
            'instance': instance,
            'name': getattr(instance, 'name', name),
            'description': getattr(instance, 'description', 'No description'),
            'version': getattr(instance, 'version', '1.0.0'),
            'icon': getattr(instance, 'icon', 'puzzle'),
            'is_system': getattr(instance, 'is_system_module', False),
            'loaded_at': int(time.time())
        }
        
        cls._dependencies[name] = dependencies or []
    
    @classmethod
    def unregister_module(cls, name: str):
        """Unregister a module from the registry"""
        cls._modules.pop(name, None)
        cls._dependencies.pop(name, None)
    
    @classmethod
    def get_module_info(cls, name: str = None):
        """Get information about modules"""
        if name:
            return cls._modules.get(name)
        return cls._modules.copy()
    
    @classmethod
    def get_dependencies(cls, name: str):
        """Get dependencies for a module"""
        return cls._dependencies.get(name, [])
    
    @classmethod
    def check_dependencies_met(cls, name: str):
        """Check if all dependencies for a module are loaded"""
        dependencies = cls.get_dependencies(name)
        missing = [dep for dep in dependencies if dep not in cls._modules]
        return len(missing) == 0, missing