import discord
from discord.ext import commands
import importlib
import os
import sys
import asyncio
from flask import Flask, render_template_string, request, jsonify
import threading
import json

# Bot configuration
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
WEB_PORT = 5000

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Flask app for web dashboard
app = Flask(__name__)

# Store loaded modules
loaded_modules = {}

# Dashboard HTML template
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Discord Bot Dashboard</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #2c2f33;
            color: white;
        }
        .navbar {
            background-color: #23272a;
            padding: 1rem;
            display: flex;
            gap: 1rem;
        }
        .nav-button {
            background-color: #7289da;
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            cursor: pointer;
            text-decoration: none;
            border-radius: 4px;
        }
        .nav-button:hover {
            background-color: #5b6eae;
        }
        .content {
            padding: 2rem;
        }
        .module-content {
            display: none;
        }
        .module-content.active {
            display: block;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <button class="nav-button" onclick="showModule('home')">Home</button>
        {% for module_name in modules %}
        <button class="nav-button" onclick="showModule('{{ module_name }}')">{{ modules[module_name].name }}</button>
        {% endfor %}
    </div>
    <div class="content">
        <div id="home" class="module-content active">
            <h1>Discord Bot Dashboard</h1>
            <p>Select a module from the navigation bar to get started.</p>
            <h3>Loaded Modules:</h3>
            <ul>
            {% for module_name in modules %}
                <li>{{ modules[module_name].name }} - {{ modules[module_name].description }}</li>
            {% endfor %}
            </ul>
        </div>
        {% for module_name in modules %}
        <div id="{{ module_name }}" class="module-content">
            {{ modules[module_name].html|safe }}
        </div>
        {% endfor %}
    </div>
    <script>
        function showModule(moduleName) {
            document.querySelectorAll('.module-content').forEach(el => {
                el.classList.remove('active');
            });
            document.getElementById(moduleName).classList.add('active');
        }
    </script>
</body>
</html>
'''

def load_modules():
    """Load all modules from the modules directory"""
    modules_dir = "modules"
    if not os.path.exists(modules_dir):
        os.makedirs(modules_dir)
        return
    
    for filename in os.listdir(modules_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            try:
                # Import the module
                spec = importlib.util.spec_from_file_location(
                    module_name, 
                    os.path.join(modules_dir, filename)
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                # Initialize the module
                if hasattr(module, 'setup'):
                    module_instance = module.setup(bot, app)
                    loaded_modules[module_name] = module_instance
                    print(f"Loaded module: {module_name}")
            except Exception as e:
                print(f"Failed to load module {module_name}: {e}")

@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_TEMPLATE, modules=loaded_modules)

@app.route('/api/<module_name>/<action>', methods=['GET', 'POST'])
def module_api(module_name, action):
    """Handle API requests for modules"""
    if module_name in loaded_modules:
        module = loaded_modules[module_name]
        if hasattr(module, 'handle_api'):
            return module.handle_api(action, request)
    return jsonify({"error": "Module or action not found"}), 404

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Web dashboard running on http://localhost:{WEB_PORT}')

def run_flask():
    """Run Flask in a separate thread"""
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)

def main():
    # Load modules
    load_modules()
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Run the bot
    bot.run(BOT_TOKEN)

if __name__ == "__main__":
    main()