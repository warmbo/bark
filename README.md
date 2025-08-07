# Bark: A Modular Self-Hosted Discord Bot
Bark is a modular, self-hosted Discord bot designed for ease of use and extensibility.  It features a web-based dashboard for management and a hot-reloading module system, allowing developers to add custom functionality without restarting the bot.  This allows for rapid development and testing of new features.

## Features
* **Modular Architecture:**  A flexible plugin system with hot-reloading capabilities.  New modules can be added and existing ones updated on the fly.
* **Web-Based Dashboard:** A modern, responsive web interface provides real-time monitoring and management of the bot and its modules.
* **Real-time Module Management:** Enable, disable, and reload modules directly from the dashboard. View module-specific statistics.
* **Message Sending (Web Interface):**  Send messages as the bot through the dashboard.
* **Built-in Modules:** Several useful modules are included out of the box, including server statistics, a message sender, weather information, and an insult generator.
* **Extensible:** Developers can easily create custom modules using provided templates to add their own unique features.
* **Hot Reloading:** Modules automatically reload after changes are made without requiring a bot restart.
* **Persistent Storage:** Uses an SQLite database to store persistent data.
* **Error Handling:** Robust error handling throughout the application.

## Usage
1. **Run the Bot:** Execute `python bot.py` from the command line.  This starts both the Discord bot and the web dashboard.
2. **Access the Dashboard:** Open your web browser and navigate to `http://localhost:5000`.
3. **Manage Modules:** The dashboard provides an interface to enable, disable, and reload modules.
4. **Use Bot Commands:**  Use the bot's commands (e.g., `!help`, `!weather`, `!bite`) within your Discord server.
5. **Send Messages (Admin):**  Use the "Speak As Bot" module (Admin access only) on the web dashboard to send messages to your Discord channels.

## Installation
1. **Clone the Repository:**
   ```bash
   git clone https://github.com/yourusername/bark.git
   cd bark
   ```
2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure Environment:** Create a `.env` file based on the `.env.example` file, providing your Discord bot token.
   ```
   cp .env.example .env
   ```
4. **Run the Bot:**
   ```bash
   python bot.py
   ```

## Technologies Used
* **Python:** The primary programming language for the bot and its modules.
* **discord.py:**  A robust Python library for interacting with the Discord API.
* **Flask:** A lightweight Python web framework for building the bot's dashboard.
* **watchdog:** A Python library for monitoring file system changes (used for hot reloading).
* **aiohttp:** An asynchronous HTTP client for making API requests (used in weather module).
* **python-dotenv:** A library for loading environment variables from a `.env` file.
* **SQLite:**  A lightweight embedded database used for persistent storage of bot data.

## Configuration
The bot's configuration is managed through a `.env` file.  The following environment variables can be set:

* `BOT_TOKEN`: Your Discord bot token (required).
* `WEB_PORT`: The port number for the web dashboard (defaults to 5000).
* `BOT_PREFIX`: The prefix for bot commands (defaults to `!`).

## API Documentation
The web dashboard exposes several API endpoints:

* `/api/dashboard/stats`:  Returns bot-wide statistics (servers, members, online members).
    * **Request:** `GET /api/dashboard/stats`
    * **Response:** `{"servers": 10, "members": 500, "online": 300}`

* `/api/<module_name>/<action>`:  Handles API requests for individual modules.  Specific actions vary per module. See module documentation for details.

## Dependencies
The project's dependencies are listed in `requirements.txt`.  Install them using `pip install -r requirements.txt`.

## Contributing
Contributions are welcome! Please see the contribution guidelines in the `docs/contributing.md` file (if it exists).

## Testing
Testing is currently done through the hot reloading functionality in development.  More robust testing solutions are planned.

## License
TBD

*README.md was made with [Etchr](https://etchr.dev)*