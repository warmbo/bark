# Bark: A Modular Self-Hosted Discord Bot

Bark is a modular, self-hosted Discord bot designed for simplicity and extensibility. It features a web-based dashboard for management and a hot-reloading module system that allows developers to add custom functionality without restarting the bot.

![Bark Logo](static/bark.png)

## ✨ Key Features

- **🔥 Hot Reloading**: Modules automatically reload when files are changed - no bot restarts needed
- **🌐 Web Dashboard**: Modern, responsive glass-morphism UI for real-time bot management
- **🧩 Modular Architecture**: Drop-in module system with dependency management
- **⚡ Real-time Management**: Enable/disable modules, send messages, and view statistics instantly
- **🎨 Customizable Themes**: Built-in theme system with color customization
- **🔒 System Modules**: Core functionality protected from accidental disabling
- **📊 Live Statistics**: Real-time server and member statistics

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Discord Bot Token
- Basic knowledge of Discord bot setup

### Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/bark.git
   cd bark
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your Discord bot token:
   ```env
   BOT_TOKEN=your_discord_bot_token_here
   WEB_PORT=5000
   BOT_PREFIX=bark-
   ```

4. **Run Bark**
   ```bash
   python bot.py
   ```

5. **Access Dashboard**
   Open `http://localhost:5000` in your browser

## 📁 Project Structure

```
bark/
├── bot.py                    # Main bot entry point
├── module_manager.py         # Module loading and hot-reload system
├── loader.py                 # Filesystem module scanner
├── utils.py                  # Base classes and utilities
├── requirements.txt          # Python dependencies
├── .env.example             # Environment template
├── module_config.json       # Module enable/disable state
│
├── templates/
│   └── dashboard.html       # Main dashboard template
│
├── static/
│   ├── css/
│   │   ├── base.css        # Core layout and variables
│   │   ├── components.css  # UI components
│   │   └── modules.css     # Module-specific styles
│   └── js/
│       └── dashboard.js    # Dashboard functionality
│
├── modules/                 # User modules directory
│   └── example.py           # Example module
│
└── system_modules/          # Core system modules
    └── settings.py         # Settings and module management
```



## 🎮 Using Bark

### Discord Commands
- `bark-ping` - Check bot latency
- `bark-modules` - List all loaded modules
- `bark-reload <module>` - Reload a specific module (Admin only)
- `bark-github` - Show GitHub repository information
- `bark-release` - Show latest release information

### Web Dashboard Features
- **Real-time Statistics**: Server count, member count, online members
- **Module Management**: Enable/disable modules with toggle switches
- **Theme Customization**: Change colors and apply preset themes
- **System Information**: View bot configuration and logs
- **GitHub Integration**: Live repository data and quick links

## 🧩 Module Development

Bark uses a powerful module system that supports hot reloading and dependency management.

### Creating a Basic Module

Create a new file in the `modules/` directory:

```python
# modules/my_module.py
from utils import BaseModule, APIHelpers, format_module_html
import discord

class MyModule(BaseModule):
    def __init__(self, bot, app):
        self.name = "My Module"
        self.description = "Description of what this module does"
        self.icon = "puzzle"
        self.version = "1.0.0"
        
        super().__init__(bot, app)

    def _register_commands(self):
        @self.command(name="hello", help="Say hello!")
        async def hello_cmd(ctx):
            embed = self.create_embed(
                "👋 Hello!",
                "Hello from my custom module!",
                discord.Color.green()
            )
            await ctx.send(embed=embed)

    def get_html(self):
        content = '''
        <div class="info-section">
            <h3 class="section-title">
                <i data-lucide="heart"></i>
                My Module
            </h3>
            <p>This is my custom module interface!</p>
            
            <button class="btn btn-primary" onclick="testFunction()">
                Test Button
            </button>
        </div>
        
        <script>
        function testFunction() {
            alert('Module button clicked!');
        }
        </script>
        '''
        return format_module_html('my_module', self.name, self.description, self.icon, content)

    def handle_api(self, action, request):
        if action == "test":
            return APIHelpers.standard_success_response({"message": "Test successful!"})
        return APIHelpers.standard_error_response("Unknown action", 404)

def setup(bot, app):
    return MyModule(bot, app)
```

### Module Features

- **Hot Reloading**: Files automatically reload when saved
- **Command Registration**: Use the `@self.command()` decorator
- **Web Interface**: Implement `get_html()` for dashboard integration
- **API Endpoints**: Handle web requests with `handle_api()`
- **Error Handling**: Built-in error handling and logging

### System vs Regular Modules

- **Regular Modules** (`modules/`): Can be enabled/disabled by users
- **System Modules** (`system_modules/`): Core functionality, cannot be disabled

## 🎨 Customization

### Themes
Access the Settings module to:
- Change primary colors
- Adjust border radius of dashboard
- Adjust font-size
- Apply preset themes (Ocean Blue, Forest Green, Royal Purple, etc.)
- Reset to defaults

### Module Configuration
- Enable/disable modules through the web interface
- Hot-reload modules during development
- View module dependencies and status

## 🔧 Configuration

### Environment Variables
```env
BOT_TOKEN=your_bot_token_here      # Required: Discord bot token
WEB_PORT=5000                      # Web dashboard port
BOT_PREFIX=bark-                   # Command prefix
```

### Development Guidelines
- Follow the module template structure
- Include proper error handling
- Add meaningful docstrings and comments
- Test both Discord commands and web interfaces
- Ensure hot reloading works correctly

## 📝 License

This project is open source and available under the [MIT License](LICENSE).

## 🎯 Roadmap

- [ ] Module library
- [ ] Advanced permissions system
- [ ] Database system for modules to use

---