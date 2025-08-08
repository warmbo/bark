# utils/api_helpers.py
import asyncio
from flask import jsonify
from functools import wraps

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