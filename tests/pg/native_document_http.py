"""Real loopback HTTP for native-document negotiation, never header emulation.

The original stock/alat profiles keep their reviewed transport; a factory
also owns the shared browser fixture. Native profile ASGI response messages
pass through unchanged; a gate delays their original start. Native SSE remains
live and closes with its actual browser connection. No app lifespan is started.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import itertools
import os
from pathlib import Path
import re
import socket
from urllib.parse import parse_qsl


_SHARED_RECEIPTS = itertools.count(1)


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


async def bounded_cleanup(step, operation, *, timeout=5, cancel_timeout=1, owned_tasks=None):
    """A cancellation-resistant close must not make fixture teardown hang."""
    result = dict(step=step, status='FAIL', forced=False, pending=False)
    try:
        job = asyncio.ensure_future(operation())
    except BaseException as error:
        result['error_type'] = type(error).__name__
        return result
    if owned_tasks is not None:
        owned_tasks.add(job)
    done, _ = await asyncio.wait({job}, timeout=timeout)
    if not done:
        result.update(forced=True, error_type='TimeoutError')
        job.cancel()
        settled, _ = await asyncio.wait({job}, timeout=cancel_timeout)
        result['pending'] = not bool(settled)
        if settled and not job.cancelled():
            job.exception()  # consume only an already-finished exception
        if settled and owned_tasks is not None:
            owned_tasks.discard(job)
        return result
    if owned_tasks is not None:
        owned_tasks.discard(job)
    if job.cancelled():
        result['error_type'] = 'CancelledError'
    else:
        error = job.exception()
        if error is None:
            result['status'] = 'PASS'
        else:
            result['error_type'] = type(error).__name__
    return result


def wire_receipt(transport):
    """Never persist cookie/token/header/query values or browser error text."""
    rows = []
    for call in transport.requests if transport else ():
        h = call['headers']
        rows.append(dict(path=call['path'], query_present=bool(call['query_names']),
            native_navigation=call['navigation_request'], status=call.get('status'),
            sec_fetch_mode_present='sec-fetch-mode' in h,
            sec_fetch_mode_navigate=h.get('sec-fetch-mode') == 'navigate',
            sec_fetch_dest_present='sec-fetch-dest' in h,
            sec_fetch_dest_document=h.get('sec-fetch-dest') == 'document',
            sec_fetch_dest_empty=h.get('sec-fetch-dest') == 'empty',
            x_pindah_present='x-pindah' in h, x_pindah_one=h.get('x-pindah') == '1',
            x_kerangka_present='x-kerangka-halaman' in h,
            x_kerangka_zero=h.get('x-kerangka-halaman') == '0'))
    return rows


def save_cleanup_receipt(result, *, profile, engine, width):
    raw = os.environ.get('DETAIL_OUT')
    if not raw:
        return None
    out = Path(raw)
    source = Path(__file__).resolve().parents[2]
    if (not out.is_absolute() or out.is_symlink() or not out.is_dir()
            or out.stat().st_uid != os.getuid() or profile not in {'stock', 'alat', 'shared'}
            or engine not in {'chromium', 'webkit'} or type(width) is not int
            or not 1 <= width <= 4096):
        raise AssertionError('Unsafe native HTTP evidence destination')
    out = out.resolve()
    if out == source or source in out.parents or out in source.parents:
        raise AssertionError('Native HTTP evidence must stay outside source')
    suffix = '-'+str(next(_SHARED_RECEIPTS)) if profile=='shared' else ''
    path = out / f'native-document-{profile}-{engine}-{width}{suffix}-cleanup.json'
    # An accidental repeat in the same output must fail, never overwrite proof.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return path.name


def finish_cleanup(result, primary):
    """Secondary cleanup failure cannot replace the original test exception."""
    if result['status'] == 'PASS':
        return
    if primary is not None:
        primary.native_http_cleanup = result
        if hasattr(primary, 'add_note'):
            primary.add_note('Native HTTP cleanup also failed; secondary steps: ' + ', '.join(
                row['step'] for row in result['steps'] if row['status'] != 'PASS') + '. Inspect exclusive DETAIL_OUT receipt.')
        return
    raise AssertionError('Owned native HTTP cleanup failed: ' + ', '.join(
        row['step'] for row in result['steps'] if row['status'] != 'PASS'))


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
async def owned_http_browser(client, width, *, profile, transport_factory=None, fixed_port=None):
    """Shared owned lifecycle; each test transport declares its own read policy."""
    import uvicorn
    from app.main import app
    from playwright.async_api import async_playwright

    engine = os.environ.get('UJI_BROWSER', os.environ.get('OWNER_BROWSER', 'chromium'))
    assert engine in {'chromium', 'webkit'}, engine
    # The frozen owner network guard already permits this HTTP port. Never
    # retry another port if it belongs to an active PWA/other fixture worker.
    if fixed_port is not None:
        assert fixed_port==59364 and profile=='shared'
    port = fixed_port if fixed_port is not None else 59364 if os.environ.get('PWA_GUARD') else 0
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_task = context = browser = server = transport = pw = None
    primary = None
    startup = asyncio.Event()
    cleanup = dict(status='FAIL', steps=[], forced=False, primary_error_type=None)
    cleanup_tasks = set()
    try:
        listener.bind(('127.0.0.1', port))
        listener.listen(128)
        listener.setblocking(False)
        origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        transport = transport_factory(app, origin) if transport_factory else NativeDocumentHTTP(app, profile, origin)
        if hasattr(transport, 'start'):
            await transport.start()

        class ReadyServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    startup.set()

        server = ReadyServer(uvicorn.Config(transport, lifespan='off', access_log=False,
            log_level='error', proxy_headers=False, timeout_graceful_shutdown=None))
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
            done, _ = await asyncio.wait({ready}, timeout=1)
            assert done, 'Startup observer did not settle'

        # Own driver shutdown explicitly too; an async context-manager exit
        # would otherwise introduce another unbounded cleanup await.
        pw = await async_playwright().start()
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
        yield page, transport
    except BaseException as error:
        primary = error
        cleanup['primary_error_type'] = type(error).__name__
        raise
    finally:
        if transport:
            transport.closing = True
            transport.release()
        # Close native browser connections before the server, including SSE.
        for step, resource, method in (('context_close', context, 'close'),
                                       ('browser_close', browser, 'close'),
                                       ('playwright_stop', pw, 'stop')):
            if resource is not None:
                try:
                    result = await bounded_cleanup(step, getattr(resource, method), owned_tasks=cleanup_tasks)
                except BaseException as error:
                    result = dict(step=step, status='FAIL', forced=True, pending=True, error_type=type(error).__name__)
                cleanup['steps'].append(result)
        if server:
            server.should_exit = True
        if server_task:
            step = await bounded_cleanup('server_shutdown', lambda: asyncio.shield(server_task), timeout=10)
            cleanup['steps'].append(step)
        if server_task and cleanup['steps'][-1]['status'] != 'PASS':
            cleanup['forced'] = True
            if server:
                server.force_exit = True
                for connection in list(server.server_state.connections):
                    try:
                        connection.transport.abort()
                    except BaseException as error:
                        cleanup['steps'].append(dict(step='force_connection_abort', status='FAIL',
                            forced=True, pending=False, error_type=type(error).__name__))
            owned = set(transport.active if transport else ())
            if server:
                owned.update(server.server_state.tasks)
            owned.add(server_task)
            for task in owned:
                task.cancel()
            done, pending = await asyncio.wait(owned, timeout=2)
            for task in done:
                if not task.cancelled():
                    task.exception()
            cleanup['steps'].append(dict(step='forced_owned_task_drain', status='FAIL',
                forced=True, pending=bool(pending), remaining_count=len(pending)))
        remaining = {task for task in cleanup_tasks if not task.done()}
        if remaining:
            for task in remaining:
                task.cancel()
            done, pending = await asyncio.wait(remaining, timeout=2)
            for task in done:
                if not task.cancelled():
                    task.exception()
            cleanup['steps'].append(dict(step='forced_close_task_drain', status='FAIL',
                forced=True, pending=bool(pending), remaining_count=len(pending)))
        for child in getattr(server, 'servers', ()):
            try:
                child.close()
            except BaseException as error:
                cleanup['steps'].append(dict(step='listener_server_close', status='FAIL',
                    forced=False, pending=False, error_type=type(error).__name__))
        try:
            listener.close()
        except BaseException as error:
            cleanup['steps'].append(dict(step='listener_socket_close', status='FAIL',
                forced=False, pending=False, error_type=type(error).__name__))
        if transport and hasattr(transport, 'restore'):
            cleanup['steps'].append(await bounded_cleanup('restore_owned_client', transport.restore, owned_tasks=cleanup_tasks))
        cleanup['forced'] = cleanup['forced'] or any(s['forced'] for s in cleanup['steps'])
        cleanup['resources'] = dict(listener_closed=listener.fileno() == -1,
            servers_closed=all(not child.is_serving() for child in getattr(server, 'servers', ())),
            server_task_done=server_task is None or server_task.done(),
            pending_close_tasks=sum(not task.done() for task in cleanup_tasks),
            active_calls=len(transport.active) if transport else 0,
            connections=len(server.server_state.connections) if server else 0,
            protocol_error_count=len(transport.errors) if transport else 0,
            foreign_request_count=len(transport.foreign) if transport else 0)
        r = cleanup['resources']
        complete = (r['listener_closed'] and r['servers_closed'] and r['server_task_done']
                    and not any(r[k] for k in ('pending_close_tasks', 'active_calls', 'connections', 'protocol_error_count', 'foreign_request_count')))
        cleanup['status'] = 'PASS' if complete and not cleanup['forced'] and all(s['status'] == 'PASS' for s in cleanup['steps']) else 'FAIL'
        cleanup.update(profile=profile, width=width, engine=engine,
            helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            wire=wire_receipt(transport),
            gates=transport.cleanup_metadata() if transport and hasattr(transport, 'cleanup_metadata') else {name:dict(count=getattr(transport, name).jumlah,
                entered=getattr(transport, name).mulai.is_set(), released=getattr(transport, name).lepas.is_set(),
                completed=getattr(transport, name).selesai.is_set()) for name in ('html', 'data')} if transport else {})
        try:
            save_cleanup_receipt(cleanup, profile=profile, engine=engine, width=width)
        except BaseException as error:
            cleanup['status'] = 'FAIL'
            cleanup['steps'].append(dict(step='exclusive_cleanup_receipt', status='FAIL',
                forced=False, pending=False, error_type=type(error).__name__))
        finish_cleanup(cleanup, primary)


@asynccontextmanager
async def native_document_browser(client, width, *, profile):
    """Original stock/alat API, retaining the reviewed native transport."""
    async with owned_http_browser(client, width, profile=profile) as result:
        yield result
