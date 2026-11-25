"""The PUBLIC client-portal listener: the only thing that should face the internet.

It passes a request on to StudioOS only when BOTH are true: the address is under STUDIOOS_PORTAL_DOMAIN, and the path is the
portal page ('/') or starts with /portal-api/. Everything else (the staff app, /api/, /docs, /mcp, the WhatsApp webhook) is answered
"Not found" right here, without ever reaching StudioOS. The staff address stays private (Tailscale). StudioOS's own startup and
scheduler run only on the main listener, never here."""
from __future__ import annotations

from .client_portal_routes import is_portal_host
from .main import app as studioos_app

_NOT_FOUND = [(b'content-type', b'text/plain; charset=utf-8'), (b'cache-control', b'no-store'),
              (b'x-content-type-options', b'nosniff')]


def _host(scope) -> str:
    for name, value in scope.get('headers', []):
        if name == b'host':
            return value.decode('latin-1')
    return ''


async def app(scope, receive, send):
    kind = scope['type']
    if kind == 'lifespan':
        while True:
            message = await receive()
            if message['type'] == 'lifespan.startup':
                await send({'type': 'lifespan.startup.complete'})
            elif message['type'] == 'lifespan.shutdown':
                await send({'type': 'lifespan.shutdown.complete'})
                return
    path = scope.get('path', '')
    if kind == 'http' and is_portal_host(_host(scope)) and (path == '/' or path.startswith('/portal-api/')):
        await studioos_app(scope, receive, send)
        return
    if kind == 'websocket':
        await send({'type': 'websocket.close', 'code': 1008})
        return
    await send({'type': 'http.response.start', 'status': 404, 'headers': _NOT_FOUND})
    await send({'type': 'http.response.body', 'body': b'Not found'})
