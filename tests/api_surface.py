"""The API surface of StudioOS: every route, its methods, its handler and the dependencies it declares.

Used by tests/test_api_surface_snapshot.py. The snapshot is the safety net named in the launch roadmap for
splitting `main.py`: a split that moves code between files must leave this surface identical, and a release
that adds or changes an endpoint shows up as a reviewable diff to the snapshot file.

What it covers: the route table (path, HTTP methods), the handler's name, and the names of every FastAPI
dependency the route declares, including nested ones (for example the logged-in-user and database-session
dependencies). What it does NOT cover: permission checks written inside a handler's body. Those are covered
by the existing behaviour tests (tests/test_ticket_guards.py, tests/test_v0160_app.py and the access tests).

Regenerate after an intended change (never to make a failing check pass without reading the diff):

    python -m tests.api_surface --write
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent / 'fixtures' / 'api_surface.json'


def _label(call) -> str:
    """A module-independent name for a handler or dependency.

    Module paths are left out on purpose: splitting `main.py` moves handlers between files, and that must not
    change the snapshot. Values captured by a closure are kept, so `permit('admin')` and `permit('finance')`
    stay different (the role checks are the permission rules this snapshot exists to protect).
    """
    name = getattr(call, '__qualname__', getattr(call, '__name__', repr(call)))
    captured = []
    for cell in (getattr(call, '__closure__', None) or ()):
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        items = list(value) if isinstance(value, (tuple, list, set, frozenset)) else [value]
        if items and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in items):
            captured.append(repr(tuple(sorted(items, key=str)) if isinstance(value, (set, frozenset)) else value))
    return name + (f'[{",".join(captured)}]' if captured else '')


def _dependency_names(dependant) -> list[str]:
    names: list[str] = []
    for dep in dependant.dependencies:
        call = dep.call
        if call is not None:
            names.append(_label(call))
        names.extend(_dependency_names(dep))
    return names


def _depends_name(depends) -> str:
    return _label(getattr(depends, 'dependency', depends))


def _walk(routes, prefix: str = '', inherited: tuple = ()):
    """Yield (full_path, APIRoute, dependencies attached by include_router) for every route, however nested.

    Newer FastAPI keeps `include_router` results as nested `_IncludedRouter` objects instead of copying their
    routes into `app.routes`; older versions copy them. Both shapes are handled so a FastAPI upgrade cannot
    make routes disappear from the snapshot without a visible change in the route count.
    """
    from fastapi.routing import APIRoute
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route, inherited
            continue
        inner = getattr(route, 'original_router', None)
        context = getattr(route, 'include_context', None)
        if inner is not None and context is not None:
            extra = tuple(_depends_name(d) for d in (getattr(context, 'dependencies', None) or []))
            yield from _walk(inner.routes, prefix + (getattr(context, 'prefix', '') or ''), inherited + extra)


def current_surface(app=None) -> dict:
    """Return a stable, sorted description of the app's routes."""
    if app is None:
        from studioos.main import app as imported  # imported late: it reads settings from the environment
        app = imported
    routes = []
    mounts = []
    for full_path, route, inherited in _walk(app.routes):
        handler = route.endpoint
        routes.append({
            'path': full_path,
            'methods': sorted(route.methods or []),
            'handler': handler.__qualname__,
            'dependencies': sorted(set(_dependency_names(route.dependant)) | set(inherited)),
            'status_code': route.status_code,
        })
    from fastapi.routing import APIRoute
    for route in app.routes:
        # Routers included with include_router are walked above; what is left (static mount, the framework's
        # own /docs, /redoc and /openapi.json) is recorded as is, because exposing them is part of the surface.
        if not isinstance(route, APIRoute) and type(route).__name__ != '_IncludedRouter':
            mounts.append({'path': getattr(route, 'path', ''), 'kind': type(route).__name__})
    routes.sort(key=lambda r: (r['path'], r['methods']))
    mounts.sort(key=lambda m: (m['path'], m['kind']))
    return {
        'note': 'API surface snapshot. Regenerate with: python -m tests.api_surface --write',
        'route_count': len(routes),
        'routes': routes,
        'other_routes': mounts,
    }


def open_routes(surface: dict) -> list[str]:
    """Routes that declare no user, admin or role dependency, so a person need not be logged in to reach them."""
    guarded = ('current_user', 'require', 'admin')
    return sorted(f'{" ".join(r["methods"])} {r["path"]}' for r in surface['routes']
                  if not any(any(g in d.lower() for g in guarded) for d in r['dependencies']))


def _prepare_environment() -> None:
    """Same disposable settings the test suite uses; never a real database."""
    os.environ.setdefault('DATABASE_URL', 'sqlite:///./data/api_surface_snapshot.db')
    os.makedirs('data', exist_ok=True)
    os.environ.setdefault('STUDIOOS_ADMIN_PASSWORD', 'stage1-test-password-very-long')
    os.environ.setdefault('STUDIOOS_ADMIN_USERNAME', 'admin')
    os.environ.setdefault('STUDIOOS_PROVIDER', 'demo')
    os.environ.setdefault('STUDIOOS_SCHEDULER', 'off')


def main(argv: list[str]) -> int:
    if '--write' not in argv:
        print('Pass --write to (re)generate tests/fixtures/api_surface.json')
        return 2
    _prepare_environment()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    surface = current_surface()
    surface['reviewed_open_routes'] = open_routes(surface)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(surface, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(f'wrote {SNAPSHOT} with {surface["route_count"]} routes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
