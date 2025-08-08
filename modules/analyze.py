import requests
from discord import Embed

class AnalyzeModule:
    name = "Site Analyze"
    version = "1.0.0"
    description = "Show page performance and Lighthouse analysis using Microlink API."
    icon = "chart-bar"

    API_URL = "https://api.microlink.io"

    def __init__(self, bot):
        self.bot = bot
        self.api_key = None  # Add your Microlink API key here if you want

    def get_analysis(self, url):
        params = {
            "lighthouse": "true",
            "meta": "false"
        }
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            resp = requests.get(self.API_URL, params={"url": url, **params}, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data["data"].get("lighthouse", {})
            return None
        except Exception as e:
            print(f"Error fetching analysis: {e}")
            return None

    async def send_analysis(self, ctx, url):
        if not url.startswith("http"):
            url = "https://" + url

        analysis = self.get_analysis(url)
        if not analysis:
            await ctx.send(f"❌ Could not get analysis data for `{url}`.")
            return

        categories = analysis.get("categories", {})
        performance = categories.get("performance", {}).get("score", 0) * 100
        accessibility = categories.get("accessibility", {}).get("score", 0) * 100
        best_practices = categories.get("best-practices", {}).get("score", 0) * 100
        seo = categories.get("seo", {}).get("score", 0) * 100

        timings = analysis.get("timings", {})
        total_load_time = timings.get("total", 0)
        page_size = analysis.get("pageStats", {}).get("totalByteWeight", 0) / 1024  # KB

        embed = Embed(
            title=f"📊 Performance Analysis for {url}",
            color=0x4287f5
        )
        embed.add_field(name="Performance Score", value=f"{performance:.0f}%", inline=True)
        embed.add_field(name="Accessibility", value=f"{accessibility:.0f}%", inline=True)
        embed.add_field(name="Best Practices", value=f"{best_practices:.0f}%", inline=True)
        embed.add_field(name="SEO", value=f"{seo:.0f}%", inline=True)
        embed.add_field(name="Total Load Time", value=f"{total_load_time} ms", inline=True)
        embed.add_field(name="Page Size", value=f"{page_size:.1f} KB", inline=True)

        await ctx.send(embed=embed)

    def register_commands(self):
        if "analyze" in self.bot.all_commands:
            self.bot.remove_command("analyze")

        @self.bot.command(name="analyze", help="Get page performance and Lighthouse scores. Usage: !analyze <url>")
        async def analyze_cmd(ctx, url: str = None):
            if not url:
                await ctx.send("❌ Please provide a URL. Example: `!analyze example.com`")
                return
            await self.send_analysis(ctx, url)

def setup(bot, app=None):
    mod = AnalyzeModule(bot)
    mod.register_commands()
    return mod
