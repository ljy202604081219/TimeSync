"""ASGI middleware that caps the whole request body before it is parsed.

The per-endpoint 6 MB check in ``read_image`` runs after Starlette has already
buffered and parsed the multipart body, so it cannot protect memory or the
tunnel. This middleware sits in front of routing and rejects oversized bodies
from the declared Content-Length, or while streaming when a client uses chunked
encoding. The per-field and per-image checks stay in place as defence in depth.
"""
import json

from . import config

TOO_LARGE = object()


class BodyTooLarge(Exception):
    pass


class BodySizeLimit:
    def __init__(self, app, max_bytes=None):
        self.app = app
        self._max_bytes = max_bytes

    @property
    def max_bytes(self):
        # Read per request so MAX_REQUEST_BYTES can be changed without a rebuild.
        return int(self._max_bytes if self._max_bytes is not None else config.max_request_bytes())

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') in ('GET', 'HEAD', 'OPTIONS', 'DELETE'):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get('headers') or [])
        declared = headers.get(b'content-length')
        if declared:
            try:
                if int(declared) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                pass

        received = 0
        state = {'started': False}

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > self.max_bytes:
                    raise BodyTooLarge()
            return message

        async def tracked_send(message):
            if message['type'] == 'http.response.start':
                state['started'] = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyTooLarge:
            if state['started']:
                raise
            await self._reject(send)

    async def _reject(self, send):
        limit_mb = self.max_bytes / (1024 * 1024)
        body = json.dumps({'detail': f'请求体超过 {limit_mb:.1f} MB 上限，请压缩截图或改用手动录入。'}, ensure_ascii=False).encode()
        await send({
            'type': 'http.response.start',
            'status': 413,
            'headers': [
                (b'content-type', b'application/json; charset=utf-8'),
                (b'content-length', str(len(body)).encode()),
                (b'connection', b'close'),
            ],
        })
        await send({'type': 'http.response.body', 'body': body})
