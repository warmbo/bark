import os
import sys
import importlib
import importlib.util
import traceback
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import threading
import json

class ModuleManager:
    def __init__(self, bot, app, modules_dir="modules"):
        self.bot = bot
        self.app = app
        self.modules_dir = modules_dir
        self.loaded_modules = {}
        self.module_configs = {}
        self.observer = None
        self.config_file = "module_config.json"
        
        # Load module configurations
        self.load_module_configs()
        
        # Clean up config to only include existing modules
        self.cleanup_module_configs()
        
        # Ensure modules directory exists
        os.makedirs(modules_dir, exist_ok=True)
        
        # Start file watcher for hot reloading
        self.start_file_watcher()
    
    def get_available_modules(self):
        """Get list of available module files"""
        available = []
        if os.path.exists(self.modules_dir):
            for filename in os.listdir(self.modules_dir):
                if filename.endswith('.py') and filename != '__init__.py':
                    available.append(filename[:-3])  # Remove .py extension
        return available
    
    def load_module_configs(self):
        """Load module configurations from file"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.module_configs = json.load(f)
            except Exception as e:
                print(f"Error loading module configs: {e}")
                self.module_configs = {}
        else:
            self.module_configs = {}
    
    def cleanup_module_configs(self):
        """Remove configs for modules that no longer exist and clean up config structure"""
        available_modules = set(self.get_available_modules())
        configured_modules = set(self.module_configs.keys())
        
        # Remove configs for modules that don't exist anymore
        removed_modules = configured_modules - available_modules
        for module_name in removed_modules:
            del self.module_configs[module_name]
            print(f"🗑️ Removed config for missing module: {module_name}")
        
        # Add default configs for new modules and clean existing configs
        new_modules = available_modules - configured_modules
        for module_name in new_modules:
            self.module_configs[module_name] = {"enabled": True}
            print(f"➕ Added default config for new module: {module_name}")
        
        # Clean up existing configs to only have 'enabled' field
        for module_name in self.module_configs:
            if module_name in available_modules:
                # Preserve only the enabled status, remove any extra fields
                enabled_status = self.module_configs[module_name].get("enabled", True)
                self.module_configs[module_name] = {"enabled": enabled_status}
        
        # Save if any changes were made
        if removed_modules or new_modules:
            self.save_module_configs()
    
    def save_module_configs(self):
        """Save module configurations to file"""
        try:
            # Ensure all configs only have the 'enabled' field before saving
            clean_configs = {}
            for module_name, config in self.module_configs.items():
                clean_configs[module_name] = {"enabled": config.get("enabled", True)}
            
            with open(self.config_file, 'w') as f:
                json.dump(clean_configs, f, indent=2)
        except Exception as e:
            print(f"Error saving module configs: {e}")
    
    def force_clean_config(self):
        """Force clean the config file to remove any extra fields"""
        print("🧹 Force cleaning module config...")
        self.cleanup_module_configs()
        self.save_module_configs()
        print("✅ Config cleaned!")
    
    def load_module(self, filename):
        """Load a single module"""
        if not filename.endswith(".py") or filename == "__init__.py":
            return False
        
        module_name = filename[:-3]
        module_path = os.path.join(self.modules_dir, filename)
        
        try:
            # Check if module is disabled
            if not self.module_configs.get(module_name, {}).get('enabled', True):
                print(f"Module {module_name} is disabled, skipping...")
                return False
            
            # Unload existing module if it exists
            if module_name in self.loaded_modules:
                self.unload_module(module_name)
            
            # Load module spec
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if not spec or not spec.loader:
                print(f"Could not load spec for module: {module_name}")
                return False
            
            # Create and execute module
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            # Setup module if it has a setup function
            if hasattr(module, 'setup'):
                try:
                    module_instance = module.setup(self.bot, self.app, self)
                except TypeError:
                    module_instance = module.setup(self.bot, self.app)
                self.loaded_modules[module_name] = module_instance

                # Ensure clean config structure - only store enabled status
                if module_name not in self.module_configs:
                    self.module_configs[module_name] = {"enabled": True}
                    self.save_module_configs()

                print(f"✓ Loaded module: {module_name}")
                return True
            else:
                print(f"✗ Module {module_name} has no setup function")
                return False
                
        except Exception as e:
            print(f"✗ Failed to load module {module_name}: {e}")
            print(traceback.format_exc())
            return False
    
    def unload_module(self, module_name):
        """Unload a module"""
        try:
            if module_name in self.loaded_modules:
                module_instance = self.loaded_modules[module_name]
                
                # Call cleanup if available
                if hasattr(module_instance, 'cleanup'):
                    module_instance.cleanup()
                
                # Remove commands added by this module
                if hasattr(module_instance, 'commands'):
                    for cmd_name in module_instance.commands:
                        if cmd_name in self.bot.all_commands:
                            self.bot.remove_command(cmd_name)
                
                # Try to remove commands by checking if they were added by this module
                # This is a fallback method - modules should track their own commands
                commands_to_remove = []
                for cmd_name, cmd in self.bot.all_commands.items():
                    # Check if command might belong to this module
                    if hasattr(cmd, 'callback') and hasattr(cmd.callback, '__module__'):
                        if module_name in cmd.callback.__module__:
                            commands_to_remove.append(cmd_name)
                
                for cmd_name in commands_to_remove:
                    self.bot.remove_command(cmd_name)
                
                # Remove from loaded modules
                del self.loaded_modules[module_name]
                
                # Remove from sys.modules if present
                if module_name in sys.modules:
                    del sys.modules[module_name]
                
                print(f"✓ Unloaded module: {module_name}")
                return True
        except Exception as e:
            print(f"✗ Error unloading module {module_name}: {e}")
            return False
    
    def reload_module(self, module_name):
        """Reload a specific module"""
        filename = f"{module_name}.py"
        return self.load_module(filename)
    
    def load_all_modules(self):
        """Load all modules from the modules directory"""
        if not os.path.exists(self.modules_dir):
            print(f"Modules directory {self.modules_dir} does not exist")
            return
        
        # First, cleanup configs to sync with available modules
        self.cleanup_module_configs()
        
        loaded_count = 0
        for filename in os.listdir(self.modules_dir):
            if self.load_module(filename):
                loaded_count += 1
        
        print(f"Loaded {loaded_count} modules")
    
    def enable_module(self, module_name):
        """Enable a module"""
        # Only allow enabling modules that actually exist
        if module_name not in self.get_available_modules():
            return False
        
        # Ensure config exists with minimal structure
        if module_name not in self.module_configs:
            self.module_configs[module_name] = {"enabled": True}
        else:
            # Only update the enabled field, preserve clean structure
            self.module_configs[module_name]["enabled"] = True
        
        self.save_module_configs()
        
        # Try to load the module
        filename = f"{module_name}.py"
        if os.path.exists(os.path.join(self.modules_dir, filename)):
            return self.load_module(filename)
        return False
    
    def disable_module(self, module_name):
        """Disable a module"""
        # Only allow disabling modules that actually exist
        if module_name not in self.get_available_modules():
            return False
        
        # Ensure config exists with minimal structure
        if module_name not in self.module_configs:
            self.module_configs[module_name] = {"enabled": False}
        else:
            # Only update the enabled field, preserve clean structure
            self.module_configs[module_name]["enabled"] = False
        
        self.save_module_configs()
        
        # Unload if currently loaded
        if module_name in self.loaded_modules:
            return self.unload_module(module_name)
        return True
    
    def get_module_info(self):
        """Get information about all modules"""
        available_modules = self.get_available_modules()
        
        info = {
            'loaded': {},
            'available': {},
            'configs': self.module_configs
        }
        
        # Get loaded module info
        for name, module in self.loaded_modules.items():
            info['loaded'][name] = {
                'name': getattr(module, 'name', name),
                'description': getattr(module, 'description', 'No description'),
                'version': getattr(module, 'version', '1.0.0'),
                'icon': getattr(module, 'icon', 'puzzle'),
                'enabled': self.module_configs.get(name, {}).get('enabled', True)
            }
        
        # Get available module files
        for module_name in available_modules:
            if module_name not in info['loaded']:
                info['available'][module_name] = {
                    'name': module_name,
                    'enabled': self.module_configs.get(module_name, {}).get('enabled', True),
                    'loaded': False
                }
        
        return info
    
    def start_file_watcher(self):
        """Start watching for file changes for hot reloading"""
        if not os.path.exists(self.modules_dir):
            return
        
        class ModuleChangeHandler(FileSystemEventHandler):
            def __init__(self, module_manager):
                self.module_manager = module_manager
                self.last_modified = {}
            
            def on_modified(self, event):
                if event.is_directory:
                    return
                
                if event.src_path.endswith('.py'):
                    # Debounce rapid file changes
                    now = time.time()
                    if event.src_path in self.last_modified:
                        if now - self.last_modified[event.src_path] < 1:
                            return
                    
                    self.last_modified[event.src_path] = now
                    
                    filename = os.path.basename(event.src_path)
                    module_name = filename[:-3]
                    
                    print(f"📁 File changed: {filename}")
                    
                    # Reload module after a short delay
                    def reload_delayed():
                        time.sleep(0.5)  # Small delay to ensure file is fully written
                        self.module_manager.reload_module(module_name)
                    
                    threading.Thread(target=reload_delayed, daemon=True).start()
            
            def on_created(self, event):
                if event.is_directory:
                    return
                
                if event.src_path.endswith('.py'):
                    filename = os.path.basename(event.src_path)
                    module_name = filename[:-3]
                    
                    print(f"📁 New module file: {filename}")
                    
                    # Add to config and potentially load
                    self.module_manager.cleanup_module_configs()
            
            def on_deleted(self, event):
                if event.is_directory:
                    return
                
                if event.src_path.endswith('.py'):
                    filename = os.path.basename(event.src_path)
                    module_name = filename[:-3]
                    
                    print(f"📁 Module file deleted: {filename}")
                    
                    # Unload module and clean up config
                    if module_name in self.module_manager.loaded_modules:
                        self.module_manager.unload_module(module_name)
                    
                    # Clean up config
                    self.module_manager.cleanup_module_configs()
        
        try:
            self.observer = Observer()
            event_handler = ModuleChangeHandler(self)
            self.observer.schedule(event_handler, self.modules_dir, recursive=False)
            self.observer.start()
            print(f"🔄 Hot reloading enabled for {self.modules_dir}")
        except Exception as e:
            print(f"Could not start file watcher: {e}")
    
    def stop_file_watcher(self):
        """Stop the file watcher"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop_file_watcher()
        for module_name in list(self.loaded_modules.keys()):
            self.unload_module(module_name)