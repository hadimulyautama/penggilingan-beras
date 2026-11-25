"""Stock owner tests use the actual app directly, not an HTTPX trampoline.

Dynamic gates delay only native response.start. Native authentication, cookies,
SSE, compressed response messages and errors are never replaced or filtered.
No client.request hooks or synthetic response controls are supported here.
"""
import asyncio
from contextlib import asynccontextmanager

from tests.pg.native_document_http import NativeDocumentHTTP, owned_http_browser


BASE = 'http://127.0.0.1:59364'


class StockOwnerHTTP(NativeDocumentHTTP):
    def __init__(self, app, origin):
        assert origin == BASE
        self.native_app = app
        self.owner_data = dict(gates={}, gate_headers={}, gets=[], posts=[], errors=[], completed={})
        self.held = set()
        self.wire_proofs = []
        super().__init__(self.forward_native, 'stock-owner', origin)
        # The base class keeps its ResponseGate self.data for the old profiles.
        self.owner_data['posts'], self.owner_data['errors'] = self.writes, self.errors

    async def forward_native(self, scope, receive, send):
        path = scope['path']
        if path != '/api/aliran': self.owner_data['gets'].append(path)
        headers = {k.decode(): v.decode() for k, v in scope['headers']
            if k in {b'x-pindah', b'x-kerangka-halaman'}}
        required = self.owner_data['gate_headers'].get(path, {})
        gate = self.owner_data['gates'].pop(path, None) if all(
            headers.get(k) == v for k, v in required.items()) else None
        if gate: self.held.add(gate[1])
        wire = dict(path=path, status=None, mime=None, bytes=0,
            native_bytes=True, asgi_end_forwarded=False)
        self.wire_proofs.append(wire)

        async def forward(message):
            if message['type'] == 'http.response.start':
                wire.update(status=message['status'], mime=dict(message['headers']).get(
                    b'content-type', b'').split(b';')[0].decode())
                if gate:
                    gate[0].set()
                    await asyncio.wait_for(gate[1].wait(), 30)
            elif message['type'] == 'http.response.body':
                wire['bytes'] += len(message.get('body', b''))
            await send(message)  # preserve the original native message and order
            if message['type'] == 'http.response.body' and not message.get('more_body', False):
                wire['asgi_end_forwarded'] = True

        try:
            return await self.native_app(scope, receive, forward)
        finally:
            if gate:
                self.held.discard(gate[1])
                completed = self.owner_data['completed'].get(path)
                if completed: completed.set()

    def release(self):
        super().release()
        for _, release in list(self.owner_data['gates'].values()): release.set()
        for release in tuple(self.held): release.set()

    def cleanup_metadata(self):
        return dict(actual_HTTP=True, direct_native_ASGI=True, HTTPX_trampoline=False,
            native_SSE_unbuffered=True, EventSource_replaced=False, scaffold=False,
            wire=self.wire_proofs, held_gates=len(self.held))


@asynccontextmanager
async def peramban_stock(client, width):
    async with owned_http_browser(client, width, profile='stock-owner', fixed_port=59364,
            transport_factory=lambda app, origin: StockOwnerHTTP(app, origin)) as (page, transport):
        yield page, transport.owner_data
