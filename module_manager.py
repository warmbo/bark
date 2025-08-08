# module_manager.py (improved version with system modules support)
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
from collections import defaultdict, deque

class ModuleManager:
    def __init__(self, bot, app, modules_dir="modules"):
        self.bot = bot
        self.app = app
        self.modules_dir = modules_dir
        self.system_modules_dir = "system_modules"
        self.loaded_modules = {}
        self.module_configs = {}
        self.module_dependencies = defaultdict(list)
        self.observer = None
        self.system_observer = None
        self.config_file = "module_config.json"
        self._load_lock = threading.Lock()
        
        # Load module configurations
        self.load_module_configs()
        
        # Clean up config to only include existing modules
        self.cleanup_module_configs()
        
        # Ensure directories exist
        os.makedirs(modules_dir, exist_ok=True)
        os.makedirs(self.system_modules_dir, exist_ok=True)
        
        # Start file watchers for hot reloading
        self.start_file_watcher()
        self.start_system_file_watcher()
    
    def get_available_modules(self):
        """Get list of available module files from both directories"""
        available = []
        
        # Regular modules
        if os.path.exists(self.modules_dir):
            for filename in os.listdir(self.modules_dir):
                if (filename.endswith('.py') and 
                    filename != '__init__.py' and 
                    not filename.startswith('.')):
                    available.append(filename[:-3])  # Remove .py extension
        
        # System modules
        if os.path.exists(self.system_modules_dir):
            for filename in os.listdir(self.system_modules_dir):
                if (filename.endswith('.py') and 
                    filename != '__init__.py' and 
                    not filename.startswith('.')):
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
        """Remove configs for modules that no longer exist"""
        available_modules = set(self.get_available_modules())
        configured_modules = set(self.module_configs.keys())
        
        # Remove configs for modules that don't exist anymore
        removed_modules = configured_modules - available_modules
        for module_name in removed_modules:
            del self.module_configs[module_name]
            print(f"🗑️ Removed config for missing module: {module_name}")
        
        # Add default configs for new modules
        new_modules = available_modules - configured_modules
        for module_name in new_modules:
            self.module_configs[module_name] = {"enabled": True}
            print(f"➕ Added default config for new module: {module_name}")
        
        # Clean up existing configs to only have 'enabled' field
        for module_name in list(self.module_configs.keys()):
            if module_name in available_modules:
                enabled_status = self.module_configs[module_name].get("enabled", True)
                self.module_configs[module_name] = {"enabled": enabled_status}
        
        # Save if any changes were made
        if removed_modules or new_modules:
            self.save_module_configs()
    
    def save_module_configs(self):
        """Save module configurations to file"""
        try:
            clean_configs = {}
            for module_name, config in self.module_configs.items():
                clean_configs[module_name] = {"enabled": config.get("enabled", True)}
            
            with open(self.config_file, 'w') as f:
                json.dump(clean_configs, f, indent=2)
        except Exception as e:
            print(f"Error saving module configs: {e}")
    
    def _get_module_dependencies(self, module_path):
        """Extract dependencies from a module file without loading it"""
        try:
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Look for dependency declarations in comments or class attributes
            dependencies = []
            lines = content.split('\n')
            
            for line in lines:
                line = line.strip()
                # Look for dependency comments: # DEPENDENCIES: module1, module2
                if line.startswith('# DEPENDENCIES:'):
                    deps = line.replace('# DEPENDENCIES:', '').strip()
                    dependencies.extend([dep.strip() for dep in deps.split(',') if dep.strip()])
                # Look for class attribute: dependencies = ['module1', 'module2']
                elif 'dependencies' in line and '=' in line and '[' in line:
                    # Simple parsing - could be improved
                    if 'self.dependencies' in line:
                        continue  # Skip instance assignments
                    try:
                        # Extract list content
                        start = line.find('[')
                        end = line.find(']')
                        if start != -1 and end != -1:
                            deps_str = line[start+1:end]
                            # Parse simple string list
                            for dep in deps_str.split(','):
                                dep = dep.strip().strip('\'"')
                                if dep:
                                    dependencies.append(dep)
                    except:
                        pass
            
            return dependencies
        except Exception as e:
            print(f"Error reading dependencies from {module_path}: {e}")
            return []
    
    def _resolve_load_order(self, modules_to_load):
        """Resolve module load order based on dependencies"""
        # Build dependency graph
        dep_graph = {}
        in_degree = defaultdict(int)
        
        for module_name in modules_to_load:
            # Check both regular and system modules directories
            module_path = os.path.join(self.modules_dir, f"{module_name}.py")
            if not os.path.exists(module_path):
                module_path = os.path.join(self.system_modules_dir, f"{module_name}.py")
            
            dependencies = self._get_module_dependencies(module_path)
            
            dep_graph[module_name] = dependencies
            for dep in dependencies:
                if dep in modules_to_load:  # Only count dependencies we're actually loading
                    in_degree[module_name] += 1
            
            # Ensure all modules are in in_degree
            if module_name not in in_degree:
                in_degree[module_name] = 0
        
        # Topological sort using Kahn's algorithm
        queue = deque([module for module in modules_to_load if in_degree[module] == 0])
        result = []
        
        while queue:
            current = queue.popleft()
            result.append(current)
            
            # Check all modules that depend on current
            for module_name, dependencies in dep_graph.items():
                if current in dependencies and module_name in modules_to_load:
                    in_degree[module_name] -= 1
                    if in_degree[module_name] == 0:
                        queue.append(module_name)
        
        # Check for circular dependencies
        if len(result) != len(modules_to_load):
            remaining = set(modules_to_load) - set(result)
            print(f"⚠️ Circular dependencies detected in modules: {remaining}")
            # Add remaining modules anyway (they'll fail if dependencies aren't met)
            result.extend(remaining)
        
        return result
    
    def load_module_from_path(self, filename, module_path):
        """Load a single module from a specific path"""
        if not filename.endswith(".py") or filename == "__init__.py":
            return False
        
        module_name = filename[:-3]
        
        with self._load_lock:
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
                        # Use consistent setup signature
                        module_instance = module.setup(self.bot, self.app)
                        
                        # Check dependencies if module has them
                        if hasattr(module_instance, 'dependencies'):
                            missing_deps = []
                            for dep in module_instance.dependencies:
                                if dep not in self.loaded_modules:
                                    missing_deps.append(dep)
                            
                            if missing_deps:
                                print(f"⚠️ Module {module_name} has unmet dependencies: {missing_deps}")
                                # Don't fail - just warn
                        
                        self.loaded_modules[module_name] = module_instance
                        
                        # Ensure clean config structure
                        if module_name not in self.module_configs:
                            self.module_configs[module_name] = {"enabled": True}
                            self.save_module_configs()
                        
                        # Determine module type for logging
                        is_system = getattr(module_instance, 'is_system_module', False)
                        module_type = "SYSTEM" if is_system else "REGULAR"
                        print(f"✓ Loaded {module_type} module: {module_name}")
                        return True
                    except Exception as e:
                        print(f"✗ Error in module setup for {module_name}: {e}")
                        print(traceback.format_exc())
                        return False
                else:
                    print(f"✗ Module {module_name} has no setup function")
                    return False
                    
            except Exception as e:
                print(f"✗ Failed to load module {module_name}: {e}")
                print(traceback.format_exc())
                return False
    
    def load_module(self, filename):
        """Load a single module from the regular modules directory"""
        module_path = os.path.join(self.modules_dir, filename)
        return self.load_module_from_path(filename, module_path)
    
    def unload_module(self, module_name):
        """Unload a module and check for dependents"""
        try:
            if module_name in self.loaded_modules:
                # Check if other modules depend on this one
                dependents = []
                for name, module_instance in self.loaded_modules.items():
                    if hasattr(module_instance, 'dependencies') and module_name in module_instance.dependencies:
                        dependents.append(name)
                
                if dependents:
                    print(f"⚠️ Warning: Module {module_name} is required by: {dependents}")
                
                module_instance = self.loaded_modules[module_name]
                
                # Call cleanup if available
                if hasattr(module_instance, 'cleanup'):
                    module_instance.cleanup()
                
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
        # Try regular modules first
        filename = f"{module_name}.py"
        module_path = os.path.join(self.modules_dir, filename)
        
        if os.path.exists(module_path):
            return self.load_module_from_path(filename, module_path)
        
        # Try system modules
        module_path = os.path.join(self.system_modules_dir, filename)
        if os.path.exists(module_path):
            return self.load_module_from_path(filename, module_path)
        
        print(f"✗ Module file not found for {module_name}")
        return False
    
    def load_all_modules(self):
        """Load all modules from both regular and system directories"""
        if not os.path.exists(self.modules_dir):
            print(f"Modules directory {self.modules_dir} does not exist")
            return
        
        # First, cleanup configs to sync with available modules
        self.cleanup_module_configs()
        
        # Get all available modules from both directories
        available_modules = self.get_available_modules()
        
        # Filter enabled modules
        enabled_modules = [
            name for name in available_modules 
            if self.module_configs.get(name, {}).get('enabled', True)
        ]
        
        # Resolve load order
        load_order = self._resolve_load_order(enabled_modules)
        
        print(f"Loading modules in order: {load_order}")
        
        loaded_count = 0
        for module_name in load_order:
            filename = f"{module_name}.py"
            
            # Try regular modules first
            module_path = os.path.join(self.modules_dir, filename)
            if os.path.exists(module_path):
                if self.load_module_from_path(filename, module_path):
                    loaded_count += 1
                continue
            
            # Try system modules
            module_path = os.path.join(self.system_modules_dir, filename)
            if os.path.exists(module_path):
                if self.load_module_from_path(filename, module_path):
                    loaded_count += 1
                continue
            
            print(f"⚠️ Module file not found: {module_name}")
        
        print(f"Loaded {loaded_count}/{len(enabled_modules)} modules")
    
    def enable_module(self, module_name):
        """Enable a module"""
        if module_name not in self.get_available_modules():
            return False
        
        self.module_configs[module_name] = {"enabled": True}
        self.save_module_configs()
        
        filename = f"{module_name}.py"
        
        # Try regular modules first
        module_path = os.path.join(self.modules_dir, filename)
        if os.path.exists(module_path):
            return self.load_module_from_path(filename, module_path)
        
        # Try system modules
        module_path = os.path.join(self.system_modules_dir, filename)
        if os.path.exists(module_path):
            return self.load_module_from_path(filename, module_path)
        
        return False
    
    def disable_module(self, module_name):
        """Disable a module"""
        if module_name not in self.get_available_modules():
            return False
        
        self.module_configs[module_name] = {"enabled": False}
        self.save_module_configs()
        
        if module_name in self.loaded_modules:
            return self.unload_module(module_name)
        return True
    
    def get_module_info(self):
        """Get comprehensive information about all modules"""
        available_modules = self.get_available_modules()
        
        info = {
            'loaded': {},
            'available': {},
            'configs': self.module_configs,
            'dependencies': {}
        }
        
        # Get loaded module info
        for name, module in self.loaded_modules.items():
            module_info = {
                'name': getattr(module, 'name', name),
                'description': getattr(module, 'description', 'No description'),
                'version': getattr(module, 'version', '1.0.0'),
                'icon': getattr(module, 'icon', 'puzzle'),
                'enabled': self.module_configs.get(name, {}).get('enabled', True),
                'is_system_module': getattr(module, 'is_system_module', False),
                'dependencies': getattr(module, 'dependencies', [])
            }
            info['loaded'][name] = module_info
            info['dependencies'][name] = module_info['dependencies']
        
        # Get available module files
        for module_name in available_modules:
            if module_name not in info['loaded']:
                # Try to determine if it's a system module by checking directory
                is_system = os.path.exists(os.path.join(self.system_modules_dir, f"{module_name}.py"))
                
                module_path = os.path.join(
                    self.system_modules_dir if is_system else self.modules_dir, 
                    f"{module_name}.py"
                )
                dependencies = self._get_module_dependencies(module_path)
                
                info['available'][module_name] = {
                    'name': module_name,
                    'enabled': self.module_configs.get(module_name, {}).get('enabled', True),
                    'loaded': False,
                    'is_system_module': is_system,
                    'dependencies': dependencies
                }
                info['dependencies'][module_name] = dependencies
        
        return info
    
    def start_file_watcher(self):
        """Start watching for file changes in regular modules directory"""
        if not os.path.exists(self.modules_dir):
            return
        
        class ModuleChangeHandler(FileSystemEventHandler):
            def __init__(self, module_manager):
                self.module_manager = module_manager
                self.last_modified = {}
            
            def on_modified(self, event):
                if event.is_directory or not event.src_path.endswith('.py'):
                    return
                
                # Debounce rapid file changes
                now = time.time()
                if event.src_path in self.last_modified:
                    if now - self.last_modified[event.src_path] < 1:
                        return
                
                self.last_modified[event.src_path] = now
                
                filename = os.path.basename(event.src_path)
                module_name = filename[:-3]
                
                print(f"📁 Regular module file changed: {filename}")
                
                # Reload module after a short delay
                def reload_delayed():
                    time.sleep(0.5)
                    self.module_manager.reload_module(module_name)
                
                threading.Thread(target=reload_delayed, daemon=True).start()
        
        try:
            self.observer = Observer()
            event_handler = ModuleChangeHandler(self)
            self.observer.schedule(event_handler, self.modules_dir, recursive=False)
            self.observer.start()
            print(f"🔄 Hot reloading enabled for {self.modules_dir}")
        except Exception as e:
            print(f"Could not start file watcher for {self.modules_dir}: {e}")
    
    def start_system_file_watcher(self):
        """Start watching for file changes in system modules directory"""
        if not os.path.exists(self.system_modules_dir):
            return
        
        class SystemModuleChangeHandler(FileSystemEventHandler):
            def __init__(self, module_manager):
                self.module_manager = module_manager
                self.last_modified = {}
            
            def on_modified(self, event):
                if event.is_directory or not event.src_path.endswith('.py'):
                    return
                
                # Debounce rapid file changes
                now = time.time()
                if event.src_path in self.last_modified:
                    if now - self.last_modified[event.src_path] < 1:
                        return
                
                self.last_modified[event.src_path] = now
                
                filename = os.path.basename(event.src_path)
                module_name = filename[:-3]
                
                print(f"🔧 System module file changed: {filename}")
                
                # Reload module after a short delay
                def reload_delayed():
                    time.sleep(0.5)
                    self.module_manager.reload_module(module_name)
                
                threading.Thread(target=reload_delayed, daemon=True).start()
        
        try:
            self.system_observer = Observer()
            event_handler = SystemModuleChangeHandler(self)
            self.system_observer.schedule(event_handler, self.system_modules_dir, recursive=False)
            self.system_observer.start()
            print(f"🔄 Hot reloading enabled for {self.system_modules_dir}")
        except Exception as e:
            print(f"Could not start file watcher for {self.system_modules_dir}: {e}")
    
    def stop_file_watcher(self):
        """Stop the file watchers"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
        
        if self.system_observer:
            self.system_observer.stop()
            self.system_observer.join()
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop_file_watcher()
        for module_name in list(self.loaded_modules.keys()):
            self.unload_module(module_name)