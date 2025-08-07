# modules/weather.py
import discord
from discord.ext import commands
import aiohttp
import asyncio
from flask import jsonify, request
import re

class WeatherModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Weather"
        self.description = "Get current weather information for any location"
        self.icon = "cloud"
        self.version = "1.0.0"
        self.commands = []
        self.html = self.get_html()
        
        # Weather code mappings from Open-Meteo documentation
        self.weather_codes = {
            0: {"description": "Clear sky", "emoji": "☀️"},
            1: {"description": "Mainly clear", "emoji": "🌤️"},
            2: {"description": "Partly cloudy", "emoji": "⛅"},
            3: {"description": "Overcast", "emoji": "☁️"},
            45: {"description": "Fog", "emoji": "🌫️"},
            48: {"description": "Depositing rime fog", "emoji": "🌫️"},
            51: {"description": "Light drizzle", "emoji": "🌦️"},
            53: {"description": "Moderate drizzle", "emoji": "🌦️"},
            55: {"description": "Dense drizzle", "emoji": "🌧️"},
            56: {"description": "Light freezing drizzle", "emoji": "🌨️"},
            57: {"description": "Dense freezing drizzle", "emoji": "🌨️"},
            61: {"description": "Slight rain", "emoji": "🌧️"},
            63: {"description": "Moderate rain", "emoji": "🌧️"},
            65: {"description": "Heavy rain", "emoji": "⛈️"},
            66: {"description": "Light freezing rain", "emoji": "🌨️"},
            67: {"description": "Heavy freezing rain", "emoji": "🌨️"},
            71: {"description": "Slight snow fall", "emoji": "🌨️"},
            73: {"description": "Moderate snow fall", "emoji": "❄️"},
            75: {"description": "Heavy snow fall", "emoji": "❄️"},
            77: {"description": "Snow grains", "emoji": "❄️"},
            80: {"description": "Slight rain showers", "emoji": "🌦️"},
            81: {"description": "Moderate rain showers", "emoji": "🌧️"},
            82: {"description": "Violent rain showers", "emoji": "⛈️"},
            85: {"description": "Slight snow showers", "emoji": "🌨️"},
            86: {"description": "Heavy snow showers", "emoji": "❄️"},
            95: {"description": "Thunderstorm", "emoji": "⛈️"},
            96: {"description": "Thunderstorm with slight hail", "emoji": "⛈️"},
            99: {"description": "Thunderstorm with heavy hail", "emoji": "⛈️"}
        }
        
        # US state abbreviation to full name mapping
        self.us_states = {
            'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
            'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
            'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
            'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
            'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
            'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
            'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
            'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
            'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
            'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming'
        }
        
        # Register commands
        self._register_commands()
    
    def _register_commands(self):
        """Register all commands for this module"""
        
        @self.bot.command(name='weather', aliases=['w'])
        async def weather_command(ctx, *, location=None):
            """Get current weather for a location"""
            if not location:
                embed = discord.Embed(
                    title="🌤️ Location Required",
                    description="Please provide a location!\n\n"
                              "**Examples:**\n"
                              "`bark-weather Anoka, MN`\n"
                              "`bark-weather 55070`\n"
                              "`bark-weather London, UK`\n"
                              "`bark-weather Tokyo`",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
                return
            
            # Show typing indicator while fetching
            async with ctx.typing():
                coords = await self.get_coordinates(location)
                
                if not coords:
                    embed = discord.Embed(
                        title="❌ Location Not Found",
                        description=f"Could not find coordinates for **{location}**.\n\n"
                                  "**Try these formats:**\n"
                                  "• `City, State` (e.g., Anoka, MN)\n"
                                  "• `ZIP Code` (e.g., 55070)\n" 
                                  "• `City, Country` (e.g., London, UK)\n"
                                  "• `City Name` (e.g., Tokyo)",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
                    return
                
                weather_data = await self.get_weather(coords['lat'], coords['lon'])
                
                if not weather_data:
                    embed = discord.Embed(
                        title="❌ Weather Data Unavailable",
                        description="Unable to fetch weather data at this time. Please try again later.",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
                    return
                
                embed = self.create_weather_embed(weather_data, coords['name'])
                await ctx.send(embed=embed)
        
        @self.bot.command(name='forecast', aliases=['fc'])
        async def forecast_command(ctx, *, location=None):
            """Get 3-day weather forecast for a location"""
            if not location:
                embed = discord.Embed(
                    title="🌤️ Location Required",
                    description="Please provide a location for the forecast!\n\n"
                              "**Examples:**\n"
                              "`bark-forecast Anoka, MN`\n"
                              "`bark-forecast 55070`\n"
                              "`bark-forecast Paris, France`",
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
                return
            
            async with ctx.typing():
                coords = await self.get_coordinates(location)
                
                if not coords:
                    embed = discord.Embed(
                        title="❌ Location Not Found",
                        description=f"Could not find coordinates for **{location}**.",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
                    return
                
                forecast_data = await self.get_forecast(coords['lat'], coords['lon'])
                
                if not forecast_data:
                    embed = discord.Embed(
                        title="❌ Forecast Data Unavailable",
                        description="Unable to fetch forecast data at this time.",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
                    return
                
                embed = self.create_forecast_embed(forecast_data, coords['name'])
                await ctx.send(embed=embed)
        
        # Track the commands we added
        self.commands = ['weather', 'forecast']
    
    def _preprocess_location(self, location):
        """Preprocess location to handle US state abbreviations"""
        # Check for patterns like "City, ST" or "City ST"
        patterns = [
            r'^(.+),\s*([A-Z]{2})$',  # "Anoka, MN"
            r'^(.+)\s+([A-Z]{2})$'    # "Anoka MN"
        ]
        
        for pattern in patterns:
            match = re.match(pattern, location.strip())
            if match:
                city = match.group(1).strip()
                state_abbrev = match.group(2).upper()
                
                if state_abbrev in self.us_states:
                    full_state = self.us_states[state_abbrev]
                    # Try format: "City, Full State, USA"
                    return f"{city}, {full_state}, USA"
        
        # If no US state pattern found, return original
        return location
    
    def _has_us_state_abbrev(self, location):
        """Check if location contains a US state abbreviation"""
        patterns = [
            r'\b[A-Z]{2}\b',   # Any 2-letter uppercase abbreviation
            r',\s*[A-Z]{2}$',  # Ends with comma and 2 letters
            r'\s+[A-Z]{2}$'    # Ends with space and 2 letters
        ]
        
        return any(re.search(pattern, location) for pattern in patterns)
    
    async def get_coordinates(self, location):
        """Get coordinates for a location using Open-Meteo geocoding"""
        try:
            # Preprocess location to handle US state abbreviations
            processed_location = self._preprocess_location(location)
            
            async with aiohttp.ClientSession() as session:
                # Try with processed location first
                url = f"https://geocoding-api.open-meteo.com/v1/search?name={processed_location}&count=5&language=en&format=json"
                print(f"🔍 Searching for: {processed_location} (original: {location})")
                
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('results'):
                            # If original had US state abbreviation, prioritize US results
                            if self._has_us_state_abbrev(location):
                                for result in data['results']:
                                    if result.get('country_code', '').upper() == 'US':
                                        print(f"✅ Using US result: {result['name']}, {result.get('admin1', '')}")
                                        return self._format_location_result(result)
                            
                            # Otherwise, take the first result
                            result = data['results'][0]
                            print(f"✅ Using first result: {result['name']}, {result.get('admin1', '')}")
                            return self._format_location_result(result)
                
                # If processed location didn't work, try original location
                if processed_location != location:
                    print(f"🔄 Trying original location: {location}")
                    url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=5&language=en&format=json"
                    async with session.get(url, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get('results'):
                                result = data['results'][0]
                                print(f"✅ Using original result: {result['name']}")
                                return self._format_location_result(result)
                
                # Try ZIP code if it's 5 digits
                if location.isdigit() and len(location) == 5:
                    print(f"🔢 Trying ZIP code lookup: {location}")
                    zip_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=en&format=json"
                    async with session.get(zip_url, timeout=10) as zip_response:
                        if zip_response.status == 200:
                            zip_data = await zip_response.json()
                            if zip_data.get('results'):
                                result = zip_data['results'][0]
                                print(f"✅ Using ZIP result: {result}")
                                return self._format_location_result(result)
                
                print("❌ No results found")
                return None
                
        except Exception as e:
            print(f"Error getting coordinates: {e}")
            return None
    
    def _format_location_result(self, result):
        """Format a geocoding result into a standardized format"""
        name = result['name']
        country = result.get('country', '')
        admin1 = result.get('admin1', '')  # State/Province
        
        # Format display name based on country
        if result.get('country_code', '').upper() == 'US' and admin1:
            display_name = f"{name}, {admin1}, USA"
        elif admin1:
            display_name = f"{name}, {admin1}, {country}"
        else:
            display_name = f"{name}, {country}"
        
        return {
            'lat': result['latitude'],
            'lon': result['longitude'],
            'name': display_name
        }
    
    async def get_weather(self, lat, lon):
        """Get current weather data"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,rain,weather_code,wind_speed_10m&timezone=auto"
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            print(f"Error getting weather: {e}")
            return None
    
    async def get_forecast(self, lat, lon):
        """Get forecast data"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=auto&forecast_days=3"
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            print(f"Error getting forecast: {e}")
            return None
    
    def create_weather_embed(self, weather_data, location_name):
        """Create weather embed with Fahrenheit priority"""
        current = weather_data['current']
        
        # Get weather description and emoji
        weather_code = current.get('weather_code', 0)
        weather_info = self.weather_codes.get(weather_code, {"description": "Unknown", "emoji": "❓"})
        
        # Convert temperature (Fahrenheit priority)
        temp_c = current.get('temperature_2m', 0)
        temp_f = (temp_c * 9/5) + 32
        
        # Get other data
        humidity = current.get('relative_humidity_2m', 0)
        wind_speed = current.get('wind_speed_10m', 0)
        wind_speed_mph = wind_speed * 0.621371  # Convert km/h to mph
        rain = current.get('rain', 0)
        rain_inches = rain * 0.0393701  # Convert mm to inches
        
        embed = discord.Embed(
            title=f"{weather_info['emoji']} Current Weather",
            description=f"**{location_name}**",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="🌡️ Temperature",
            value=f"**{temp_f:.1f}°F** ({temp_c:.1f}°C)",
            inline=True
        )
        
        embed.add_field(
            name="🌤️ Conditions",
            value=f"**{weather_info['description']}**",
            inline=True
        )
        
        embed.add_field(
            name="💧 Humidity",
            value=f"**{humidity}%**",
            inline=True
        )
        
        embed.add_field(
            name="💨 Wind Speed",
            value=f"**{wind_speed_mph:.1f} mph** ({wind_speed:.1f} km/h)",
            inline=True
        )
        
        if rain > 0:
            embed.add_field(
                name="🌧️ Rain",
                value=f"**{rain_inches:.2f} in** ({rain:.1f} mm)",
                inline=True
            )
        
        embed.set_footer(text="Powered by Open-Meteo • Data updates every hour")
        embed.timestamp = discord.utils.utcnow()
        
        return embed
    
    def create_forecast_embed(self, forecast_data, location_name):
        """Create forecast embed with Fahrenheit priority"""
        daily = forecast_data['daily']
        
        embed = discord.Embed(
            title="📅 3-Day Forecast",
            description=f"**{location_name}**",
            color=discord.Color.green()
        )
        
        days = ["Today", "Tomorrow", "Day 3"]
        
        for i in range(min(3, len(daily['time']))):
            date = daily['time'][i]
            max_temp = daily['temperature_2m_max'][i]
            min_temp = daily['temperature_2m_min'][i]
            weather_code = daily['weather_code'][i]
            
            weather_info = self.weather_codes.get(weather_code, {"description": "Unknown", "emoji": "❓"})
            
            # Fahrenheit priority
            max_temp_f = (max_temp * 9/5) + 32
            min_temp_f = (min_temp * 9/5) + 32
            
            embed.add_field(
                name=f"{weather_info['emoji']} {days[i]} ({date})",
                value=f"**High:** {max_temp_f:.1f}°F ({max_temp:.1f}°C)\n"
                      f"**Low:** {min_temp_f:.1f}°F ({min_temp:.1f}°C)\n"
                      f"**Conditions:** {weather_info['description']}",
                inline=False
            )
        
        embed.set_footer(text="Powered by Open-Meteo")
        embed.timestamp = discord.utils.utcnow()
        
        return embed
    
    def get_html(self):
        """Return the HTML for this module's interface"""
        return '''
        <div class="module-header">
            <h2><i data-lucide="cloud"></i> Weather</h2>
            <p>Get current weather and forecasts for any location worldwide.</p>
        </div>
        
        <div class="weather-container">
            <div class="commands-section">
                <h3>📋 Commands</h3>
                <div class="command-list">
                    <div class="command-item">
                        <code>bark-weather &lt;location&gt;</code>
                        <span>Get current weather for a location</span>
                    </div>
                    <div class="command-item">
                        <code>bark-forecast &lt;location&gt;</code>
                        <span>Get 3-day forecast for a location</span>
                    </div>
                    <div class="command-item">
                        <code>bark-w &lt;location&gt;</code>
                        <span>Short alias for weather command</span>
                    </div>
                </div>
            </div>
            
            <div class="test-section">
                <h3>🧪 Test Weather API</h3>
                <div class="form-group">
                    <input type="text" id="test-location" placeholder="Enter location (e.g., London, Tokyo)" value="London">
                </div>
                <button class="btn btn-primary" onclick="testWeatherAPI()">
                    <i data-lucide="cloud"></i>
                    Get Weather
                </button>
                <div id="weather-result" class="api-result"></div>
            </div>
            
            <div class="info-section">
                <h3>ℹ️ Information</h3>
                <p><strong>API:</strong> Open-Meteo (Free, no API key required)</p>
                <p><strong>Features:</strong> Current weather, 3-day forecasts, global coverage</p>
                <p><strong>Data:</strong> Temperature, humidity, wind, precipitation, conditions</p>
                <p><strong>Updates:</strong> Hourly</p>
                <p><strong>Supported formats:</strong> City names, "City, Country", coordinates</p>
            </div>
        </div>
        
        <style>
        .weather-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
        }
        
        .commands-section, .test-section, .info-section {
            background: var(--glass-bg);
            backdrop-filter: var(--blur);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 1.5rem;
        }
        
        .commands-section h3, .test-section h3, .info-section h3 {
            margin-bottom: 1rem;
            color: var(--text);
        }
        
        .command-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }
        
        .command-item {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        
        .command-item code {
            background: var(--background);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            color: var(--primary);
            font-weight: bold;
        }
        
        .command-item span {
            color: var(--text-muted);
            font-size: 0.9rem;
        }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        .form-group input {
            width: 100%;
        }
        
        .api-result {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
            min-height: 60px;
            color: var(--text);
        }
        
        .api-result.loading {
            color: var(--text-muted);
            text-align: center;
        }
        
        .api-result.error {
            color: #ef4444;
        }
        
        .weather-display {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        
        .weather-stat {
            background: var(--background);
            border-radius: 6px;
            padding: 0.75rem;
            text-align: center;
        }
        
        .weather-stat-label {
            color: var(--text-muted);
            font-size: 0.8rem;
            margin-bottom: 0.25rem;
        }
        
        .weather-stat-value {
            color: var(--text);
            font-weight: bold;
            font-size: 1.1rem;
        }
        
        .info-section p {
            margin: 0.5rem 0;
            color: var(--text-muted);
        }
        
        .info-section p strong {
            color: var(--text);
        }
        </style>
        
        <script>
        async function testWeatherAPI() {
            const location = document.getElementById('test-location').value.trim();
            const resultDiv = document.getElementById('weather-result');
            
            if (!location) {
                resultDiv.textContent = 'Please enter a location';
                resultDiv.className = 'api-result error';
                return;
            }
            
            resultDiv.textContent = 'Loading weather data...';
            resultDiv.className = 'api-result loading';
            
            try {
                const response = await fetch('/api/weather/test_weather', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ location: location })
                });
                
                const data = await response.json();
                
                if (data.weather) {
                    const weather = data.weather;
                    resultDiv.innerHTML = `
                        <div style="margin-bottom: 1rem;">
                            <h4>${weather.emoji} ${weather.location}</h4>
                        </div>
                        <div class="weather-display">
                            <div class="weather-stat">
                                <div class="weather-stat-label">Temperature</div>
                                <div class="weather-stat-value">${weather.temperature}</div>
                            </div>
                            <div class="weather-stat">
                                <div class="weather-stat-label">Conditions</div>
                                <div class="weather-stat-value">${weather.conditions}</div>
                            </div>
                            <div class="weather-stat">
                                <div class="weather-stat-label">Humidity</div>
                                <div class="weather-stat-value">${weather.humidity}%</div>
                            </div>
                            <div class="weather-stat">
                                <div class="weather-stat-label">Wind</div>
                                <div class="weather-stat-value">${weather.wind} mph</div>
                            </div>
                        </div>
                    `;
                    resultDiv.className = 'api-result';
                } else {
                    resultDiv.textContent = data.error || 'Failed to get weather data';
                    resultDiv.className = 'api-result error';
                }
            } catch (error) {
                resultDiv.textContent = 'Error: ' + error.message;
                resultDiv.className = 'api-result error';
            }
        }
        
        // Allow Enter key to trigger search
        document.addEventListener('DOMContentLoaded', function() {
            const input = document.getElementById('test-location');
            if (input) {
                input.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        testWeatherAPI();
                    }
                });
            }
        });
        </script>
        '''
    
    def handle_api(self, action, request):
        """Handle API requests for this module"""
        if action == "test_weather":
            data = request.get_json()
            location = data.get('location')
            
            if not location:
                return jsonify({"error": "No location provided"}), 400
            
            # Run async functions in bot's event loop
            if hasattr(self.bot, 'loop') and self.bot.loop.is_running():
                try:
                    future1 = asyncio.run_coroutine_threadsafe(
                        self.get_coordinates(location),
                        self.bot.loop
                    )
                    coords = future1.result(timeout=10)
                    
                    if not coords:
                        return jsonify({"error": f"Location '{location}' not found"}), 404
                    
                    future2 = asyncio.run_coroutine_threadsafe(
                        self.get_weather(coords['lat'], coords['lon']),
                        self.bot.loop
                    )
                    weather_data = future2.result(timeout=10)
                    
                    if not weather_data:
                        return jsonify({"error": "Unable to fetch weather data"}), 500
                    
                    current = weather_data['current']
                    weather_code = current.get('weather_code', 0)
                    weather_info = self.weather_codes.get(weather_code, {"description": "Unknown", "emoji": "❓"})
                    
                    temp_c = current.get('temperature_2m', 0)
                    temp_f = (temp_c * 9/5) + 32
                    wind_speed_mph = current.get('wind_speed_10m', 0) * 0.621371
                    
                    result = {
                        "weather": {
                            "location": coords['name'],
                            "temperature": f"{temp_f:.1f}°F ({temp_c:.1f}°C)",
                            "conditions": weather_info['description'],
                            "emoji": weather_info['emoji'],
                            "humidity": current.get('relative_humidity_2m', 0),
                            "wind": f"{wind_speed_mph:.1f}"
                        }
                    }
                    
                    return jsonify(result)
                    
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
            else:
                return jsonify({"error": "Bot not ready"}), 503
        
        return jsonify({"error": "Unknown action"}), 404
    
    def cleanup(self):
        """Clean up when module is unloaded"""
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return WeatherModule(bot, app)