"""OpenAI-compatible API client with detailed error reporting."""

import httpx

from triagetty.chat.models import ChatRequest, ChatResponse


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout: float = 60.0,
        verify_tls: bool = True,
        transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.transport = transport

    async def complete(self, request: ChatRequest) -> ChatResponse:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": request.model, "messages": [m.__dict__ for m in request.messages]}
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                verify=self.verify_tls,
                transport=self.transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
            response.raise_for_status()
            return self._parse_response(response)
        except httpx.ConnectError as exc:
            raise ConnectionError(
                f"Failed to connect to {self.base_url}. "
                f"Is the LLM server running? (Connection refused or network unreachable)"
            ) from exc
        except httpx.ConnectTimeout as exc:
            raise TimeoutError(
                f"Connection to {self.base_url} timed out after {self.timeout}s. "
                f"Is the LLM server responding?"
            ) from exc
        except httpx.ReadTimeout as exc:
            raise TimeoutError(
                f"LLM server at {self.base_url} did not respond within {self.timeout}s. "
                f"The request may be too large or the server may be overloaded."
            ) from exc
        except httpx.NetworkError as exc:
            raise ConnectionError(
                f"Network error connecting to {self.base_url}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            self._handle_http_error(exc)
        except Exception as exc:
            raise RuntimeError(
                f"Unexpected error calling {self.base_url}: {type(exc).__name__}: {exc}"
            ) from exc

    def _parse_response(self, response: httpx.Response) -> ChatResponse:
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            body = response.text[:500] if response.text else "(empty)"
            raise ValueError(
                f"The model endpoint returned an unexpected response: {exc}\n"
                f"Response body: {body}"
            ) from exc
        if not isinstance(content, str):
            raise ValueError(
                f"The model endpoint returned non-text content: {type(content).__name__}"
            )
        return ChatResponse(content)

    def _handle_http_error(self, exc: httpx.HTTPStatusError) -> None:
        status = exc.response.status_code
        body = self._extract_error_body(exc.response)
        
        if status == 401:
            raise PermissionError(
                f"Authentication failed (401). Check your API key.\n"
                f"Server response: {body}"
            ) from exc
        elif status == 403:
            raise PermissionError(
                f"Access denied (403). You may not have permission to use this model.\n"
                f"Server response: {body}"
            ) from exc
        elif status == 404:
            raise ValueError(
                f"Endpoint not found (404). Check the URL: {self.base_url}\n"
                f"Server response: {body}"
            ) from exc
        elif status == 429:
            raise ValueError(
                f"Rate limit exceeded (429). Try again in a moment.\n"
                f"Server response: {body}"
            ) from exc
        elif 500 <= status < 600:
            raise RuntimeError(
                f"Server error ({status}). The LLM server encountered an error.\n"
                f"Server response: {body}"
            ) from exc
        else:
            raise ValueError(
                f"HTTP {status} error from {self.base_url}\n"
                f"Server response: {body}"
            ) from exc

    @staticmethod
    def _extract_error_body(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                return data.get("error", data.get("message", str(data)))
            return str(data)
        except Exception:
            return response.text[:500] if response.text else "(no body)"
