# modules/settings.py
from flask import jsonify, request
from utils import BaseModule, APIHelpers, format_module_html

class SettingsModule(BaseModule):
    def __init__(self, bot, app):
        self.name = "Settings"
        self.description = "Bot configuration and module management"
        self.icon = "settings"
        self.version = "1.1.0"
        # Mark as system module to prevent disabling
        self.is_system_module = True
        self.dependencies = []
        super().__init__(bot, app)
    def _register_commands(self):
        pass
    def get_html(self):
        pass
    def handle_api(self, action, request):
        pass

def setup(bot, app):
    return SettingsModule(bot, app)
