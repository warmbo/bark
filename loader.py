# loader.py
import os
import importlib.util
import logging

log = logging.getLogger("loader")
logging.basicConfig(level=logging.INFO)

MODULES_DIR = "modules"
SYSTEM_MODULES_DIR = "system_modules"

def _load_module_from_file(path, package_prefix, name):
    """
    Safely import a module from a file and return a metadata dict.
    Does not register the module into your ModuleManager; just reads attributes.
    """
    try:
        spec = importlib.util.spec_from_file_location(f"{package_prefix}.{name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        log.exception(f"Failed to import module file {path}: {e}")
        return None

    # Gather metadata with safe fallbacks
    try:
        html = getattr(module, "html", "")
        # if there is a callable to build HTML, call it (safe-wrapped)
        if callable(getattr(module, "get_html", None)):
            try:
                html = module.get_html()
            except Exception:
                log.exception(f"get_html() failed for {name}; using string html.")
    except Exception:
        html = ""

    return {
        "name": getattr(module, "name", name),
        "icon": getattr(module, "icon", "settings" if package_prefix.endswith("system_modules") else "puzzle"),
        "description": getattr(module, "description", ""),
        "version": getattr(module, "version", "1.0.0"),
        "dependencies": getattr(module, "dependencies", []),
        "html": html or "<p>No interface available</p>",
        "is_system_module": True if package_prefix.endswith("system_modules") else False,
    }

def load_modules():
    """
    Returns a dict of module_key -> metadata for both regular and system modules.
    Keys are the python filename without .py (e.g. 'settings' from settings.py).
    """
    modules = {}

    # helper
    def scan_dir(directory, package_prefix, is_system=False):
        if not os.path.isdir(directory):
            return
        for fname in os.listdir(directory):
            if not fname.endswith(".py") or fname.startswith("__"):
                continue
            key = fname[:-3]
            path = os.path.join(directory, fname)
            meta = _load_module_from_file(path, package_prefix, key)
            if not meta:
                continue
            # ensure the is_system_module flag
            meta["is_system_module"] = True if is_system else False
            modules[key] = meta

    scan_dir(MODULES_DIR, "modules", is_system=False)
    scan_dir(SYSTEM_MODULES_DIR, "system_modules", is_system=True)

    log.info(f"loader: found {len(modules)} filesystem modules ({MODULES_DIR}, {SYSTEM_MODULES_DIR})")
    return modules
