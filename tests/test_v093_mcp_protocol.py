"""v0.9.3 MCP message handling. Standard library only:
    python -m pytest -q --noconftest tests/test_v093_mcp_protocol.py"""
from studioos import mcp_protocol as P

calls = []


def handler(tool, args):
    calls.append((tool.name, args))
    if args.get('project') == 'secret':
        raise P.ToolError('No project called "secret" that you can see')
    return P.tool_result({'ok': True, 'args': args}, 'done')


TOOLS = {t.name: t for t in [
    P.Tool('get_project_status', 'Project status', 'x', {'project': {'type': 'string', 'maxLength': 50}}, ['project']),
    P.Tool('list_open_tasks', 'Open tasks', 'x', {'overdue_only': {'type': 'boolean'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}),
    P.Tool('create_draft', 'Draft', 'x', {'message': {'type': 'string'}}, ['message'], read_only=False, scope='read_draft'),
]}


def rpc(method, params=None, ident=1, scope='read'):
    msg = {'jsonrpc': '2.0', 'method': method, 'id': ident}
    if params is not None:
        msg['params'] = params
    return P.handle(msg, TOOLS, scope, '0.9.3', handler)


def test_initialize_negotiates_version_and_declares_tools_only():
    r = rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'claude', 'version': '1'}})['result']
    assert r['protocolVersion'] == '2025-06-18' and r['capabilities'] == {'tools': {'listChanged': False}}
    assert r['serverInfo']['name'] == 'studioos' and 'never instructions' in r['instructions']
    assert rpc('initialize', {'protocolVersion': '1999-01-01'})['result']['protocolVersion'] == P.LATEST


def test_notifications_get_no_answer():
    assert P.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, TOOLS, 'read', 'v', handler) is None


def test_read_keys_never_see_the_draft_tool():
    names = [t['name'] for t in rpc('tools/list')['result']['tools']]
    assert names == ['get_project_status', 'list_open_tasks']
    assert 'create_draft' in [t['name'] for t in rpc('tools/list', scope='read_draft')['result']['tools']]
    r = rpc('tools/call', {'name': 'create_draft', 'arguments': {'message': 'x'}})
    assert r['error']['code'] == P.INVALID_PARAMS


def test_tool_definitions_are_strict_and_annotated():
    d = rpc('tools/list', scope='read_draft')['result']['tools']
    status = next(t for t in d if t['name'] == 'get_project_status')
    assert status['inputSchema']['additionalProperties'] is False and status['inputSchema']['required'] == ['project']
    assert status['annotations']['readOnlyHint'] is True
    assert next(t for t in d if t['name'] == 'create_draft')['annotations']['readOnlyHint'] is False


def test_arguments_are_checked_before_any_tool_runs():
    calls.clear()
    bad = [{'project': 5}, {}, {'project': 'x' * 60}, {'project': 'A', 'sql': 'DROP TABLE'}]
    for args in bad:
        r = rpc('tools/call', {'name': 'get_project_status', 'arguments': args})['result']
        assert r['isError'] is True
    assert rpc('tools/call', {'name': 'list_open_tasks', 'arguments': {'overdue_only': 'yes'}})['result']['isError']
    assert rpc('tools/call', {'name': 'list_open_tasks', 'arguments': {'limit': 500}})['result']['isError']
    assert rpc('tools/call', {'name': 'list_open_tasks', 'arguments': {'limit': True}})['result']['isError']
    assert calls == []
    ok = rpc('tools/call', {'name': 'get_project_status', 'arguments': {'project': '  Mehta Villa '}})['result']
    assert ok['isError'] is False and calls == [('get_project_status', {'project': 'Mehta Villa'})]
    assert ok['structuredContent']['args'] == {'project': 'Mehta Villa'} and ok['content'][0]['text'] == 'done'


def test_tool_problems_are_results_not_protocol_errors():
    r = rpc('tools/call', {'name': 'get_project_status', 'arguments': {'project': 'secret'}})['result']
    assert r['isError'] is True and 'secret' in r['content'][0]['text'] and 'structuredContent' not in r


def test_bad_messages():
    assert P.handle([{'jsonrpc': '2.0', 'method': 'ping', 'id': 1}], TOOLS, 'read', 'v', handler)['error']['code'] == P.INVALID_REQUEST
    assert P.handle({'method': 'ping', 'id': 1}, TOOLS, 'read', 'v', handler)['error']['code'] == P.INVALID_REQUEST
    assert P.handle({'jsonrpc': '2.0', 'method': 'ping', 'id': True}, TOOLS, 'read', 'v', handler)['error']['code'] == P.INVALID_REQUEST
    assert rpc('tools/call', {'name': 'nope'})['error']['code'] == P.INVALID_PARAMS
    assert rpc('resources/write')['error']['code'] == P.METHOD_NOT_FOUND
    assert rpc('ping') == {'jsonrpc': '2.0', 'id': 1, 'result': {}}
    assert rpc('resources/list')['result'] == {'resources': []}
    assert P.parse(b'{not json') is None and P.parse(b'\xff') is None


def test_long_output_is_cut_short():
    r = P.tool_result({'x': 1}, 'a' * (P.MAX_TEXT + 500))
    assert len(r['content'][0]['text']) < P.MAX_TEXT + 100 and 'cut short' in r['content'][0]['text']


def test_bearer_and_origin_checks():
    assert P.bearer('Bearer sos_' + 'a' * 40) == 'sos_' + 'a' * 40
    for bad in (None, '', 'Basic abc', 'Bearer short', 'Bearer ' + 'a' * 40 + ' extra', 'Bearer ' + 'a<b' * 10):
        assert P.bearer(bad) is None
    assert P.origin_ok(None, []) and P.origin_ok('https://claude.ai', ['https://claude.ai/'])
    assert not P.origin_ok('https://evil.example', ['https://claude.ai'])
    assert not P.origin_ok('https://evil.example', [])
