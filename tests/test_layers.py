"""The architecture, enforced: every layer imports only from the layers below it, the library
(layers 0-6) needs nothing beyond Python's standard library, and `hi` only talks to the API."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "harness_interface"
CLI = ROOT / "frontend" / "cli" / "hi_cli"

LAYER = {"errors": 0, "execution": 0, "runtimes": 1, "workspace": 2, "harness": 3,
         "resources": 4, "routing": 5, "platform": 6, "api": 7}
PUBLIC_API = 6.5                                     # harness_interface/__init__.py: the library's front door


def layer_of(module: str) -> float:
    """`harness_interface.runtimes.docker` -> 1; the package itself -> the public API."""
    parts = module.split(".")
    return LAYER[parts[1]] if len(parts) > 1 else PUBLIC_API


def module_name(path: Path, root: Path, package: str) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = [package, *rel.parts]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports(path: Path, module: str) -> set[str]:
    """Every module this file imports, with relative imports made absolute."""
    found = set()
    is_package = path.name == "__init__.py"
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")
                base = base[: len(base) - node.level + (1 if is_package else 0)]
                found.add(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                found.add(node.module)
    return found


def library_modules():
    for path in sorted(PACKAGE.rglob("*.py")):
        yield path, module_name(path, PACKAGE, "harness_interface")


def test_every_module_belongs_to_a_layer():
    for _, module in library_modules():
        layer_of(module)                             # a KeyError names the stray module


def test_layers_import_only_downward():
    for path, module in library_modules():
        mine = layer_of(module)
        for name in imports(path, module):
            if name == "harness_interface" or name.startswith("harness_interface."):
                assert layer_of(name) <= mine, f"{module} (layer {mine}) imports {name} (layer {layer_of(name)})"


def test_the_library_needs_only_the_standard_library():
    for path, module in library_modules():
        if layer_of(module) >= LAYER["api"]:
            continue
        for name in imports(path, module):
            top = name.split(".")[0]
            assert top == "harness_interface" or top in sys.stdlib_module_names, f"{module} imports {name}"


def test_the_public_api_is_the_library_only():
    names = imports(PACKAGE / "__init__.py", "harness_interface")
    assert not any(n.startswith("harness_interface.api") for n in names)


def test_the_cli_only_talks_to_the_api():
    for path in CLI.rglob("*.py"):
        names = imports(path, module_name(path, CLI, "hi_cli"))
        assert not any(n.split(".")[0] == "harness_interface" for n in names), path
