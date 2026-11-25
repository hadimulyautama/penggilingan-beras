"""Real loopback HTTP for native-document negotiation, never header emulation.

Only the two reviewed read profiles use this helper. ASGI response messages
pass through unchanged; a gate delays their original start. Native SSE remains
live and closes with its actual browser connection. No app lifespan is started.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import re
import socket
from urllib.parse import parse_qsl


class ResponseGate:
    def __init__(self):
        self.mulai = asyncio.Event()
        self.lepas = asyncio.Event()
        self.selesai = asyncio.Event()
        self.jumlah = 0

    async def wait(self):
        self.jumlah += 1
        self.mulai.set()
        await asyncio.wait_for(self.lepas.wait(), 20)


def native_document(headers):
    return (headers.get('sec-fetch-mode') == 'navigate'
            and headers.get('sec-fetch-dest') in {'document', 'empty'}
            and headers.get('x-pindah') != '1')


def gate_kind(profile, path, query, headers):
    if query:
        return None
    if profile == 'stock':
        if path == '/stok' and native_document(headers):
            return 'html'
        if path == '/api/halaman-bertahap/stok':
            return 'data'
    elif (profile == 'alat' and path == '/pengaturan/alat'
            and headers.get('x-pindah') == '1'
            and headers.get('x-kerangka-halaman') == '0'):
        return 'data'
    return None


def foreign_url_pattern(origin):
    return re.compile(r'^(?!' + re.escape(origin) + r'(?:/|$)).*')


class NativeDocumentHTTP:
    def __init__(self, app, profile, origin):
        if profile not in {'stock', 'alat'}:
            raise ValueError('Unknown native-document fixture profile')
        self.app, self.profile, self.origin = app, profile, origin
        self.host = origin.removeprefix('http://').encode()
        self.html, self.data = ResponseGate(), ResponseGate()
        self.requests, self.writes, self.errors, self.foreign = [], [], [], []
        self.active = set()
        self.closing = False

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            raise AssertionError('Fixture accepts HTTP only')
        from starlette.responses import Response
        raw = dict(scope['headers'])
        if raw.get(b'host') != self.host or scope['client'][0] != '127.0.0.1':
            self.foreign.append(dict(path=scope['path'], owned_host=False))
            return await Response(status_code=403)(scope, receive, send)
        if scope['method'] != 'GET':
            self.writes.append((scope['method'], scope['path']))
            return await Response(status_code=405)(scope, receive, send)
        headers = {k.decode(): v.decode() for k, v in scope['headers'] if k in {
            b'x-pindah', b'x-kerangka-halaman', b'sec-fetch-mode', b'sec-fetch-dest'}}
        query = scope.get('query_string', b'').decode('ascii')
        allowed = {'x-pindah': {'0', '1'}, 'x-kerangka-halaman': {'0', '1'},
                   'sec-fetch-mode': {'navigate', 'cors', 'no-cors', 'same-origin'},
                   'sec-fetch-dest': {'document', 'empty', 'script', 'style', 'image', 'font'}}
        safe_headers = {k: v if v in allowed[k] else 'other' for k, v in headers.items()}
        call = dict(path=scope['path'], query_names=sorted({k for k, _ in parse_qsl(query)}),
                    headers=safe_headers, navigation_request=native_document(headers))
        self.requests.append(call)
        selected = gate_kind(self.profile, scope['path'], query, headers)
        gate = getattr(self, selected) if selected else None
        task = asyncio.current_task()
        self.active.add(task)

        async def observed_send(message):
            if message['type'] == 'http.response.start':
                call['status'] = message['status']
                if gate:
                    assert message['status'] == 200, call
                    await gate.wait()
            # No status/header/body substitution; browser receives native
            # document metadata, cookies, compressed bytes and data unchanged.
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except asyncio.CancelledError:
            if not self.closing:
                self.errors.append(dict(path=scope['path'], type='CancelledError'))
            raise
        except Exception as error:
            self.errors.append(dict(path=scope['path'], type=type(error).__name__))
            raise
        finally:
            self.active.discard(task)
            if gate:
                gate.selesai.set()

    def release(self):
        self.html.lepas.set()
        self.data.lepas.set()


@asynccontextmanager
async def native_document_browser(client, width, *, profile):
    """Existing fixture cookies/app; one owned socket, no product overrides."""
    import uvicorn
    from app.main import app
    from playwright.async_api import async_playwright

    engine = os.environ.get('UJI_BROWSER', os.environ.get('OWNER_BROWSER', 'chromium'))
    assert engine in {'chromium', 'webkit'}, engine
    # The frozen owner network guard already permits this HTTP port. Never
    # retry another port if it belongs to an active PWA/other fixture worker.
    port = 59364 if os.environ.get('PWA_GUARD') else 0
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_task = context = browser = server = transport = None
    startup = asyncio.Event()
    try:
        listener.bind(('127.0.0.1', port))
        listener.listen(128)
        listener.setblocking(False)
        origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        transport = NativeDocumentHTTP(app, profile, origin)

        class ReadyServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    startup.set()

        server = ReadyServer(uvicorn.Config(transport, lifespan='off', access_log=False,
            log_level='error', proxy_headers=False, timeout_graceful_shutdown=4))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        ready = asyncio.create_task(startup.wait())
        try:
            done, _ = await asyncio.wait({ready, server_task}, timeout=10,
                                         return_when=asyncio.FIRST_COMPLETED)
            if server_task in done:
                await server_task
            assert startup.is_set(), 'Owned native HTTP server did not start'
        finally:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)

        async with async_playwright() as pw:
            browser = await getattr(pw, engine).launch()
            context = await browser.new_context(viewport={'width': width, 'height': 900},
                service_workers='block', reduced_motion='reduce')
            # Match ONLY foreign URLs. Same-origin requests are never routed,
            # so the native document's wire Sec-Fetch/cookies stay browser-owned.
            await context.route(foreign_url_pattern(origin), lambda route: route.abort())
            await context.add_cookies([dict(name=c.name, value=c.value, url=origin)
                                      for c in client.cookies.jar])
            page = await context.new_page()
            page.on('pageerror', lambda error: transport.errors.append(str(error)))
            try:
                yield page, transport
            finally:
                transport.closing = True
                transport.release()
                # Closing the real browser connection delivers native SSE
                # disconnect before asking the owned HTTP server to stop.
                await context.close()
                context = None
                await browser.close()
                browser = None
    finally:
        if transport:
            transport.closing = True
            transport.release()
        if context:
            await context.close()
        if browser:
            await browser.close()
        if server:
            server.should_exit = True
        forced = False
        try:
            if server_task:
                await asyncio.wait_for(asyncio.shield(server_task), 10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            forced = True
            if server:
                server.force_exit = True
            if transport:
                remaining = list(transport.active)
                for task in remaining:
                    task.cancel()
                await asyncio.gather(*remaining, return_exceptions=True)
            if server_task:
                server_task.cancel()
                await asyncio.gather(server_task, return_exceptions=True)
        finally:
            listener.close()
        assert not forced, 'Owned native HTTP cleanup required forced cancellation'
        assert listener.fileno() == -1
        assert not server or all(not child.is_serving() for child in getattr(server, 'servers', ()))
        assert not server_task or server_task.done()
        assert not transport or not transport.active, 'Owned native HTTP tasks remain'
        assert not transport or not transport.foreign, transport.foreign if transport else None
        assert not transport or not transport.errors, transport.errors if transport else None
