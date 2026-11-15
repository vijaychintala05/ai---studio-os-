"""Load StudioOS's standard-library-only modules without importing the web app (no SQLAlchemy or
FastAPI needed). Used by the v0.11.0+ database-free tests and the accuracy runner."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(*names):
    out = []
    for name in names:
        if name in sys.modules and getattr(sys.modules[name], '__file__', '').startswith(str(ROOT / 'studioos')):
            out.append(sys.modules[name])
            continue
        for _ in range(10):
            spec = importlib.util.spec_from_file_location(name, ROOT / 'studioos' / f'{name}.py')
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            try:
                spec.loader.exec_module(mod)
                break
            except ModuleNotFoundError as ex:      # a stdlib-only sibling module: load it first, then retry
                del sys.modules[name]
                if not ex.name or not (ROOT / 'studioos' / f'{ex.name}.py').exists():
                    raise
                load(ex.name)
        out.append(mod)
    return out[0] if len(out) == 1 else out
