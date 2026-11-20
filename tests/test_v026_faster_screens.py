"""v0.26: screens load faster: big text responses (pages, scripts, lists) are compressed when the browser accepts it."""
from .conftest import write


def test_static_scripts_are_compressed_for_browsers_that_accept_it(client):
    r = client.get('/static/app.js', headers={'Accept-Encoding': 'gzip'})
    assert r.status_code == 200
    assert r.headers.get('content-encoding') == 'gzip'
    assert 'Vary' in r.headers and 'accept-encoding' in r.headers['Vary'].lower()


def test_small_and_uncompressed_requests_still_work(client):
    assert client.get('/static/app.js', headers={'Accept-Encoding': 'identity'}).headers.get('content-encoding') is None
    assert client.get('/health').status_code == 200


def test_the_security_headers_are_still_there_when_compressed(client):
    r = client.get('/static/app.js', headers={'Accept-Encoding': 'gzip'})
    assert "script-src 'self'" in r.headers.get('content-security-policy', '')


def test_api_answers_are_identical_compressed_or_not(admin):
    a = admin.get('/api/summary', headers={'Accept-Encoding': 'identity'}).json()
    b = admin.get('/api/summary', headers={'Accept-Encoding': 'gzip'}).json()
    assert a == b
