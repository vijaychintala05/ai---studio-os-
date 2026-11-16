"""Staff browser instances share one sync runtime while keeping browsers separate."""
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sim'))
import browser_entries as B


def fake(monkeypatch,fail_second=False):
    state=SimpleNamespace(active=False,starts=0,stops=0,launches=0,closed=0)
    class Page:
        def __getattr__(self,name):return lambda *a,**k:self
    class Browser:
        def new_page(self,**kwargs):assert kwargs['viewport']=={'width':390,'height':844};return Page()
        def close(self):state.closed+=1
    class P:
        def launch(self,**kwargs):
            state.launches+=1
            if fail_second and state.launches==2:raise RuntimeError('Fictional launch failed')
            return Browser()
        def stop(self):state.active=False;state.stops+=1
        @property
        def chromium(self):return self
    class Starter:
        def start(self):
            assert not state.active,'A second sync runtime cannot start'
            state.active=True;state.starts+=1;return P()
    monkeypatch.setattr(B,'sync_playwright',Starter)
    monkeypatch.setattr(B.BrowserEntries,'_runtime',None,raising=False);monkeypatch.setattr(B.BrowserEntries,'_leases',0,raising=False)
    return state


def test_two_staff_browsers_share_runtime_and_close_independently(monkeypatch,tmp_path):
    state=fake(monkeypatch)
    a=B.BrowserEntries('http://127.0.0.1:8880',tmp_path/'a');b=B.BrowserEntries('http://127.0.0.1:8880',tmp_path/'b')
    assert state.starts==1 and a.browser is not b.browser
    a.close();assert state.active and state.stops==0
    b.close();assert not state.active and state.stops==1 and B.BrowserEntries._leases==0
    a.close();assert state.stops==1


def test_failed_second_browser_does_not_stop_or_leak_the_first_runtime(monkeypatch,tmp_path):
    state=fake(monkeypatch,True)
    a=B.BrowserEntries('http://127.0.0.1:8880',tmp_path/'a')
    with pytest.raises(RuntimeError,match='Fictional launch failed'):B.BrowserEntries('http://127.0.0.1:8880',tmp_path/'b')
    assert state.active and B.BrowserEntries._leases==1
    a.close();assert state.stops==1 and B.BrowserEntries._runtime is None
