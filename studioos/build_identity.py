"""Public source identity, covering shipped code without reading operator data.

Version labels are hashed verbatim. The simulation also records Docker image IDs
and dependency inventories; this hash does not claim to identify OS packages.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path


def source_identity(root: Path) -> dict:
    root = Path(root).resolve()
    files = [root / 'VERSION', root / 'requirements.txt']
    for folder in ('studioos', 'agents'):
        files.extend(p for p in (root / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')
                     and not any(part.startswith('.env') for part in p.relative_to(root).parts))
    hashes = {}
    for path in sorted(files):
        if not path.resolve().is_relative_to(root):
            raise ValueError('Build source may not link outside its root')
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    encoded = json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()
    return {'version': (root / 'VERSION').read_text().strip(),
            'source_sha256': hashlib.sha256(encoded).hexdigest(), 'source_files': len(hashes)}


@lru_cache(maxsize=1)
def runtime_identity() -> dict:
    return source_identity(Path(__file__).resolve().parents[1])
