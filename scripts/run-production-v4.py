from pathlib import Path

source_path = Path(__file__).with_name("publish-nonlinear-v4-production.py")
source = source_path.read_text(encoding="utf-8")
needle = "v4 = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(v4)"
replacement = "v4 = importlib.util.module_from_spec(spec)\nimport sys\nsys.modules[spec.name] = v4\nspec.loader.exec_module(v4)"
if needle not in source:
    raise RuntimeError("PRODUCTION_V4_RUNNER_PATCH_TARGET_MISSING")
source = source.replace(needle, replacement, 1)
namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(source, str(source_path), "exec"), namespace, namespace)
