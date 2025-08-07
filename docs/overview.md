# Bark Discord Bot Documentation

## Overview

Bark is a modular, self-hosted Discord bot designed for simplicity and extensibility. It features a web-based dashboard for management and a hot-reloading module system that allows developers to add custom functionality without restarting the bot.

## Key Features

- **Modular Architecture**: Drop-in module system with hot-reloading
- **Web Dashboard**: Modern, responsive web interface for bot management
- **Real-time Management**: Enable/disable modules, send messages, and view statistics
- **Hot Reloading**: Modules automatically reload when files are changed
- **No External Dependencies**: Uses free APIs where possible (Open-Meteo, Evil Insult Generator)
- **Modern UI**: Glass-morphism design with customizable themes

## Project Structure

```
bark/
├── bot.py                 # Main bot entry point
├── module_manager.py      # Module loading and management system
├── requirements.txt       # Python dependencies
├── .env.example          # Environment configuration template
├── module_config.json    # Module enable/disable state
├── templates/
│   └── dashboard.html    # Web dashboard template
├── static/
│   ├── css/
│   │   └── dashboard.css # Dashboard styling
│   └── js/
│       └── dashboard.js  # Dashboard functionality
└── modules/              # Bot modules directory
    ├── server_stats.py   # Server statistics module
    ├── speak_as_bot.py   # Message sending module
    ├── weather.py        # Weather information module
    ├── bite.py          # Insult generator module
    └── hello-test.py    # Example test module
```

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your bot token and settings
   ```

3. **Run the Bot**:
   ```bash
   python bot.py
   ```

4. **Access Dashboard**:
   Open `http://localhost:5000` in your browser

## Built-in Modules

### Server Stats
- Display detailed server statistics
- Commands: `bark-stats`, `bark-serverstats`
- Features: Member counts, channel counts, server info, boost status

### Speak As Bot
- Send messages as the bot through web interface
- No Discord commands (web-only)
- Features: Server/channel selection, message composition

### Weather
- Current weather and forecasts using Open-Meteo API
- Commands: `bark-weather <location>`, `bark-forecast <location>`
- Features: Global coverage, multiple location formats, US state abbreviation support

### Bite (Insult Generator)
- Playful insults using Evil Insult Generator API
- Commands: `bark-bite @user`, `bark-gentlebite @user`
- Features: Safety checks, fallback insults, gentle mode

## Module Development Templates

### Basic Module Template

```python
# modules/my_module.py
import discord
from discord.ext import commands
from flask import jsonify

class MyModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "My Module"
        self.description = "Description of what this module does"
        self.icon = "puzzle"  # Lucide icon name
        self.version = "1.0.0"
        self.commands = []  # Track commands for cleanup
        self.html = self.get_html()  # Web interface HTML
        
        # Register commands
        self._register_commands()
    
    def _register_commands(self):
        """Register Discord commands"""
        @self.bot.command(name='mycommand')
        async def my_command(ctx):
            """Command description for help"""
            await ctx.send("Hello from my module!")
        
        # Track commands for cleanup
        self.commands = ['mycommand']
    
    def get_html(self):
        """Return HTML for web dashboard interface"""
        return '''
        <div class="module-header">
            <h2><i data-lucide="puzzle"></i> My Module</h2>
            <p>Module description and functionality.</p>
        </div>
        
        <div class="module-content">
            <!-- Your module's web interface here -->
        </div>
        '''
    
    def handle_api(self, action, request):
        """Handle web dashboard API requests"""
        if action == "my_action":
            # Handle API request
            return jsonify({"success": True})
        
        return jsonify({"error": "Unknown action"}), 404
    
    def cleanup(self):
        """Clean up when module is unloaded"""
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)

def setup(bot, app):
    """Required setup function"""
    return MyModule(bot, app)
```

### Advanced Module Template (with API calls)

```python
# modules/advanced_module.py
import discord
from discord.ext import commands
import aiohttp
import asyncio
from flask import jsonify, request

class AdvancedModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Advanced Module"
        self.description = "Module with external API integration"
        self.icon = "zap"
        self.version = "1.0.0"
        self.commands = []
        self.html = self.get_html()
        
        self._register_commands()
    
    def _register_commands(self):
        """Register commands with error handling"""
        @self.bot.command(name='apicommand')
        async def api_command(ctx, *, query=None):
            """Command that uses external API"""
            if not query:
                embed = discord.Embed(
                    title="❌ Missing Parameter",
                    description="Please provide a query: `bark-apicommand <query>`",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return
            
            async with ctx.typing():
                result = await self.fetch_api_data(query)
                
                if result:
                    embed = discord.Embed(
                        title="✅ API Result",
                        description=result,
                        color=discord.Color.green()
                    )
                    await ctx.send(embed=embed)
                else:
                    embed = discord.Embed(
                        title="❌ API Error",
                        description="Failed to fetch data from API",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
        
        self.commands = ['apicommand']
    
    async def fetch_api_data(self, query):
        """Fetch data from external API"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.example.com/data?q={query}"
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('result', 'No result')
                    return None
        except Exception as e:
            print(f"API Error: {e}")
            return None
    
    def get_html(self):
        """Web interface with API testing"""
        return '''
        <div class="module-header">
            <h2><i data-lucide="zap"></i> Advanced Module</h2>
            <p>Module with external API integration and testing.</p>
        </div>
        
        <div class="api-test-section">
            <h3>🧪 Test API</h3>
            <div class="form-group">
                <input type="text" id="api-query" placeholder="Enter query">
            </div>
            <button class="btn btn-primary" onclick="testAPI()">
                Test API
            </button>
            <div id="api-result" class="api-result"></div>
        </div>
        
        <script>
        async function testAPI() {
            const query = document.getElementById('api-query').value;
            const resultDiv = document.getElementById('api-result');
            
            if (!query) {
                resultDiv.textContent = 'Please enter a query';
                return;
            }
            
            resultDiv.textContent = 'Loading...';
            
            try {
                const response = await fetch('/api/advanced_module/test_api', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });
                
                const data = await response.json();
                resultDiv.textContent = data.result || data.error;
            } catch (error) {
                resultDiv.textContent = 'Error: ' + error.message;
            }
        }
        </script>
        '''
    
    def handle_api(self, action, request):
        """Handle API requests with async support"""
        if action == "test_api":
            data = request.get_json()
            query = data.get('query')
            
            if not query:
                return jsonify({"error": "No query provided"}), 400
            
            # Run async function in bot's event loop
            if hasattr(self.bot, 'loop') and self.bot.loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.fetch_api_data(query),
                        self.bot.loop
                    )
                    result = future.result(timeout=10)
                    return jsonify({"result": result or "No data"})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
            else:
                return jsonify({"error": "Bot not ready"}), 503
        
        return jsonify({"error": "Unknown action"}), 404
    
    def cleanup(self):
        """Cleanup with detailed logging"""
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return AdvancedModule(bot, app)
```

## Module Development Guidelines

### Required Components

1. **Class Structure**: Module must be a class with required attributes:
   - `name`: Display name for the module
   - `description`: Brief description of functionality
   - `icon`: Lucide icon name for UI
   - `version`: Module version string

2. **Setup Function**: Must include `setup(bot, app)` function that returns module instance

3. **Command Tracking**: Track registered commands in `self.commands` list for proper cleanup

4. **Cleanup Method**: Implement `cleanup()` method to remove commands when module is unloaded

### Best Practices

1. **Error Handling**: Always include proper error handling for Discord commands and API calls

2. **User Feedback**: Provide clear, helpful error messages and success confirmations

3. **Async Support**: Use `asyncio.run_coroutine_threadsafe()` for async operations in API handlers

4. **Web Interface**: Include HTML interface in `get_html()` method for dashboard integration

5. **API Endpoints**: Implement `handle_api(action, request)` for web dashboard functionality

6. **Validation**: Validate user input and provide helpful usage examples

7. **Documentation**: Include command descriptions and help text

### Styling Guidelines

The dashboard uses CSS custom properties for theming. Key variables:
- `--primary`: Primary brand color
- `--accent`: Accent color for highlights
- `--background`: Main background color
- `--surface`: Card/panel background
- `--text`: Primary text color
- `--text-muted`: Secondary text color

Use existing CSS classes:
- `.btn .btn-primary`: Primary buttons
- `.form-group`: Form field containers
- `.api-result`: API response display areas
- `.module-header`: Module title sections

## Module Management

### Web Dashboard
- View all loaded modules
- Enable/disable modules
- Real-time module statistics
- Send messages through web interface

### Command Line
- `bark-modules`: List all modules and their status
- `bark-reload <module>`: Reload specific module (Admin only)
- `bark-help`: Show all available commands

### Hot Reloading
Modules automatically reload when their files are modified, allowing for rapid development and testing without bot restarts.

## Contributing

1. Create new modules in the `modules/` directory
2. Follow the module templates and guidelines
3. Test both Discord commands and web interface functionality
4. Include proper error handling and user feedback
5. Document commands and API endpoints

## License

This project is designed for educational and personal use. Module developers should respect API terms of service and rate limits when integrating external services.