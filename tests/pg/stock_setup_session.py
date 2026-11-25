"""Settle issued session reads only before Stock test setup replaces a document.

This never delays the application clicks/races under test, reads a token/body,
changes a request, or filters page errors. It is not a production-cause proof.
"""
import asyncio
from contextlib import contextmanager
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary


_OWNERS = WeakKeyDictionary()


class StockSetupSessions:
    def __init__(self, page, origin):
        self.page, self.origin = page, urlsplit(origin)
        self.started = asyncio.get_running_loop().time()
        self.rows, self.faults, self.barriers = {}, [], []
        self.changed = asyncio.Event()
        self.callbacks = [('request', self.request), ('response', self.response),
            ('requestfinished', self.finished), ('requestfailed', self.failed)]

    def clock(self):
        return round((asyncio.get_running_loop().time() - self.started) * 1000, 3)

    def matches(self, request):
        u = urlsplit(request.url)
        if u.path != '/api/sesi-formulir': return False
        if ((u.scheme, u.netloc) != (self.origin.scheme, self.origin.netloc)
                or u.query or request.method != 'GET'):
            self.faults.append('Unknown session request shape'); return False
        return True

    def request(self, request):
        if not self.matches(request): return
        if request in self.rows or len(self.rows) >= 256:
            self.faults.append('Duplicate or excessive session requests'); return
        try:
            if request.frame is not self.page.main_frame:
                self.faults.append('Session request is not main-frame owned'); return
        except Exception:
            self.faults.append('Session frame unavailable'); return
        self.rows[request] = dict(id=len(self.rows) + 1, terminal=None, status=None, mime=None,
            path='/api/sesi-formulir', request_ms=self.clock(), frame_known=True, main_frame=True,
            frame_path_at_request=urlsplit(getattr(request.frame, 'url', '')).path,
            page_path_at_request=urlsplit(getattr(self.page, 'url', '')).path)

    def response(self, response):
        row = self.rows.get(response.request)
        if row is not None:
            row.update(status=response.status, response_ms=self.clock(),
                mime=response.headers.get('content-type', '').split(';')[0].strip().lower())

    def terminal(self, request, outcome):
        row = self.rows.get(request)
        if row is not None:
            if row['terminal'] is not None: self.faults.append('Duplicate session terminal event')
            row.update(terminal=outcome, terminal_ms=self.clock(),
                page_path_at_terminal=urlsplit(getattr(self.page, 'url', '')).path)
            self.changed.set()

    def finished(self, request): self.terminal(request, 'finished')
    def failed(self, request): self.terminal(request, 'failed')

    async def drain_issued(self, *, timeout=10):
        assert not self.faults, self.faults
        # Freeze the pending set now. Later periodic/focus reads are not added
        # to this barrier, and application navigation remains unmodified.
        targets = tuple(row for row in self.rows.values() if row['terminal'] is None)
        # Callback-delivery timestamps and paths only; no tokens, headers,
        # response bodies, or claim of native abort provenance is recorded.
        proof = dict(issued=len(self.rows), captured=[row['id'] for row in targets], completed=False,
            started_ms=self.clock(), before=[dict(row) for row in targets], error_type=None)
        self.barriers.append(proof)
        async def settled():
            while any(row['terminal'] is None for row in targets):
                self.changed.clear()
                if any(row['terminal'] is None for row in targets): await self.changed.wait()
        try:
            await asyncio.wait_for(settled(), timeout)
            assert not self.faults, self.faults
            assert all(row['terminal'] == 'finished' and row['status'] == 200
                and row['mime'] == 'application/json' for row in targets), targets
            proof['completed'] = True
        except BaseException as error:
            proof['error_type'] = type(error).__name__
            raise
        finally:
            proof.update(ended_ms=self.clock(), after=[dict(row) for row in targets],
                pending_captured=[row['id'] for row in targets if row['terminal'] is None],
                pending_at_exit=[dict(row) for row in self.rows.values() if row['terminal'] is None],
                faults=list(self.faults))


@contextmanager
def stock_setup_sessions(page, origin):
    assert page not in _OWNERS, 'Stock setup tracker already has an owner'
    owner = StockSetupSessions(page, origin)
    _OWNERS[page] = owner
    for event, callback in owner.callbacks: page.on(event, callback)
    try: yield owner
    finally:
        for event, callback in owner.callbacks: page.remove_listener(event, callback)
        assert _OWNERS.get(page) is owner
        del _OWNERS[page]


async def before_stock_setup_goto(page):
    assert page in _OWNERS, 'Stock setup navigation requires its owned tracker'
    await _OWNERS[page].drain_issued()
