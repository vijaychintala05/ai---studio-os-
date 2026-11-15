# Run: python tests/check_mcp_sdk_interop.py .   (needs the official "mcp" Python package; fictional data only)
"""Serve StudioOS's MCP protocol layer over HTTP exactly as studioos/mcp_routes.mcp_post
frames it (one JSON answer per POST, 202 for notifications, 405 for GET, bearer key),
with fictional tool data, and drive it with the official MCP Python SDK client."""
import sys, json, threading, time, asyncio
sys.path.insert(0, sys.argv[1])
from studioos import mcp_protocol as P
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

KEY = 'sos_' + 'k' * 43
def status(args): return P.tool_result({'project': args['project'], 'open': 3}, f"**{args['project']}** · 3 open tasks, 1 overdue")
def draft(args): return P.tool_result({'saved': False}, 'Drafted. Nothing has been saved.')
TOOLS = {t.name: t for t in [
    P.Tool('get_project_status', 'Project status', 'One project', {'project': {'type': 'string', 'maxLength': 200}}, ['project'], handler=status),
    P.Tool('create_draft', 'Create a draft', 'Draft only', {'message': {'type': 'string', 'maxLength': 2000}}, ['message'], handler=draft, read_only=False, scope='read_draft')]}
SCOPE = {'value': 'read'}
log = []

async def mcp(request):
    if request.method != 'POST':
        return Response(status_code=405, headers={'Allow': 'POST'})
    if P.bearer(request.headers.get('authorization')) != KEY:
        return JSONResponse({'error': 'key required'}, status_code=401, headers={'WWW-Authenticate': 'Bearer realm="StudioOS"'})
    message = P.parse(await request.body())
    log.append(message.get('method') if isinstance(message, dict) else None)
    response = P.handle(message, TOOLS, SCOPE['value'], '0.9.3', lambda tool, args: tool.handler(args))
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response, headers={'Cache-Control': 'no-store'})

app = Starlette(routes=[Route('/mcp', mcp, methods=['GET', 'POST', 'DELETE'])])
server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8765, log_level='warning'))
threading.Thread(target=server.run, daemon=True).start()
while not server.started: time.sleep(0.05)

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def run(key, scope):
    SCOPE['value'] = scope
    async with httpx2.AsyncClient(headers={'Authorization': f'Bearer {key}'}) as http:
        async with streamable_http_client('http://127.0.0.1:8765/mcp', http_client=http) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                r = await session.call_tool('get_project_status', {'project': 'Mehta Villa'})
                bad = await session.call_tool('get_project_status', {'project': 7})
                out = {'protocol': init.protocol_version, 'server': init.server_info.name,
                       'tools': [t.name for t in tools.tools], 'read_only_hint': tools.tools[0].annotations.read_only_hint,
                       'result_text': r.content[0].text, 'structured': r.structured_content, 'is_error': r.is_error,
                       'bad_args_is_error': bad.is_error, 'bad_args_text': bad.content[0].text}
                if scope == 'read_draft':
                    d = await session.call_tool('create_draft', {'message': 'Log expense 3,200 at Mehta Villa'})
                    out['draft_text'] = d.content[0].text
                return out

res = {'read_key': asyncio.run(run(KEY, 'read')), 'draft_key': asyncio.run(run(KEY, 'read_draft'))}
try:
    asyncio.run(run('sos_' + 'w' * 43, 'read')); res['wrong_key'] = 'ACCEPTED (bad)'
except BaseException as e:
    res['wrong_key'] = 'refused: ' + type(e).__name__
import requests
res['get_status'] = requests.get('http://127.0.0.1:8765/mcp').status_code
res['methods_seen'] = sorted(set(m for m in log if m))
print(json.dumps(res, indent=1, default=str))
server.should_exit = True
