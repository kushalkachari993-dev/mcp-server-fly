print(">>> registry.py START loading")

import importlib
import pkgutil
from pathlib import Path


def register_all_tools(mcp):
    print(">>> register_all_tools CALLED")

    tools_path = Path(__file__).parent

    for module in tools_path.iterdir():
        if module.is_dir() and module.name != "__pycache__":
            try:
                print(f"Loading tool: {module.name}")

                tool_module = importlib.import_module(
                    f"app.tools.{module.name}.tool"
                )

                if hasattr(tool_module, "register"):
                    tool_module.register(mcp)
                    print(f"Registered: {module.name}")

            except Exception as e:
                print(f"Failed to load {module.name}: {e}")