"""Optional browser-compatible HTTPS transport for public Quizlet HTML only."""
from contextlib import asynccontextmanager

import httpx
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException, Timeout


class PageResponse:
    def __init__(self, response):
        self.response = response
        self.status_code = response.status_code
        self.headers = response.headers
        self.encoding = response.encoding
        self.is_redirect = response.status_code in {301, 302, 303, 307, 308}
        self.is_success = 200 <= response.status_code < 300

    async def aiter_bytes(self):
        async for chunk in self.response.aiter_content():
            yield chunk


class BrowserPageClient:
    """Use Chrome's HTTPS profile without executing scripts or logging in."""
    async def __aenter__(self):
        self.session = AsyncSession(impersonate="chrome", timeout=25, verify=True)
        await self.session.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.session.__aexit__(*args)

    @asynccontextmanager
    async def stream(self, method, url, headers):
        # Keep Chrome's User-Agent and TLS profile consistent. fetch_page still
        # validates the exact Quizlet host and each redirect before any request.
        try:
            async with self.session.stream(method, url, allow_redirects=False,
                    headers={key: value for key, value in headers.items() if key.lower() != "user-agent"}) as response:
                yield PageResponse(response)
        except Timeout:
            raise httpx.ReadTimeout("Quizlet page timed out") from None
        except RequestException:
            raise httpx.ConnectError("Quizlet page could not be retrieved") from None
