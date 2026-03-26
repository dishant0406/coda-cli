from __future__ import annotations

import gzip
import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, quote
from urllib.request import Request, urlopen

from coda_cli.core.state import DEFAULT_API_BASE_URL


@dataclass
class CodaApiError(Exception):
    message: str
    status_code: Optional[int] = None
    details: Any = None

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"{self.status_code}: {self.message}"


class CodaBackend:
    DEFAULT_PAGE_BATCH_SIZE = 25
    TRANSIENT_HTTP_STATUS_CODES = frozenset({502, 503, 504})

    def __init__(
        self,
        api_key: str,
        api_base_url: str = DEFAULT_API_BASE_URL,
        timeout: Optional[float] = None,
        export_poll_interval: float = 1.0,
        export_max_attempts: int = 10,
    ):
        self.api_key = api_key
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout = timeout
        self.export_poll_interval = export_poll_interval
        self.export_max_attempts = export_max_attempts
        self._ssl_context = self._build_ssl_context()

    def list_documents(self, query: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", "/docs", query=self._compact_query({"query": query}))

    def get_document(self, doc_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/docs/{self._segment(doc_id)}")

    def list_pages(
        self,
        doc_id: str,
        limit: Optional[int] = None,
        next_page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/docs/{self._segment(doc_id)}/pages",
            query=self._compact_query({"limit": None if next_page_token else limit, "pageToken": next_page_token}),
        )

    def list_all_pages(
        self,
        doc_id: str,
        limit: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        items: list[Dict[str, Any]] = []
        next_page_token: Optional[str] = None
        page_number = 0
        page_batch_size = limit or self.DEFAULT_PAGE_BATCH_SIZE

        while True:
            page_number += 1
            self._report_progress(progress_callback, f"Fetching pages batch {page_number} ({len(items)} loaded)...")
            try:
                payload = self.list_pages(doc_id, limit=page_batch_size, next_page_token=next_page_token)
            except CodaApiError as exc:
                if exc.status_code in self.TRANSIENT_HTTP_STATUS_CODES:
                    raise CodaApiError(
                        "Coda timed out while listing pages for this document. "
                        "Retry the command, or narrow the search with --parent-page/--parent-path."
                    ) from exc
                raise
            items.extend(payload.get("items", []))
            next_page_token = payload.get("nextPageToken")
            if not next_page_token:
                self._report_progress(progress_callback, f"Fetched {len(items)} pages.")
                return {"items": items}

    def get_page(self, doc_id: str, page_id_or_name: str) -> Dict[str, Any]:
        return self._request("GET", f"/docs/{self._segment(doc_id)}/pages/{self._segment(page_id_or_name)}")

    def create_page(
        self,
        doc_id: str,
        name: str,
        content: Optional[str] = None,
        parent_page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/docs/{self._segment(doc_id)}/pages",
            body={
                "name": name,
                "parentPageId": parent_page_id,
                "pageContent": {
                    "type": "canvas",
                    "canvasContent": {"format": "markdown", "content": content if content is not None else " "},
                },
            },
        )

    def export_page(
        self,
        doc_id: str,
        page_id_or_name: str,
        output_format: str = "markdown",
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        self._report_progress(progress_callback, f"Exporting page as {output_format}...")
        export_job = self._request(
            "POST",
            f"/docs/{self._segment(doc_id)}/pages/{self._segment(page_id_or_name)}/export",
            body={"outputFormat": output_format},
        )

        request_id = export_job.get("id")
        if not request_id:
            raise CodaApiError("Page export did not return a request id")

        download_link = None
        for attempt in range(1, self.export_max_attempts + 1):
            self._report_progress(progress_callback, f"Polling export status ({attempt}/{self.export_max_attempts})...")
            status = self._request(
                "GET",
                f"/docs/{self._segment(doc_id)}/pages/{self._segment(page_id_or_name)}/export/{self._segment(request_id)}",
            )
            if status.get("status") == "complete":
                download_link = status.get("downloadLink")
                break
            if status.get("status") == "failed":
                raise CodaApiError(status.get("error") or "Page export failed")
            time.sleep(self.export_poll_interval)

        if not download_link:
            raise CodaApiError("Page export did not complete before the polling limit")

        self._report_progress(progress_callback, "Downloading exported page...")
        return self._request(
            "GET",
            None,
            absolute_url=download_link,
            include_auth=False,
            parse_json=False,
            response_label=f"exported page {output_format}",
        )

    def get_page_content(
        self,
        doc_id: str,
        page_id_or_name: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        return self.export_page(
            doc_id,
            page_id_or_name,
            output_format="markdown",
            progress_callback=progress_callback,
        )

    def update_page_content(
        self,
        doc_id: str,
        page_id_or_name: str,
        content: str,
        insertion_mode: str = "replace",
        element_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "contentUpdate": {
                "insertionMode": insertion_mode,
                "canvasContent": {"format": "markdown", "content": content},
            }
        }
        if element_id:
            body["contentUpdate"]["elementId"] = element_id

        return self._request(
            "PUT",
            f"/docs/{self._segment(doc_id)}/pages/{self._segment(page_id_or_name)}",
            body=body,
        )

    def rename_page(self, doc_id: str, page_id_or_name: str, new_name: str) -> Dict[str, Any]:
        return self._request(
            "PUT",
            f"/docs/{self._segment(doc_id)}/pages/{self._segment(page_id_or_name)}",
            body={"name": new_name},
        )

    def duplicate_page(self, doc_id: str, page_id_or_name: str, new_name: str) -> Dict[str, Any]:
        page_content = self.get_page_content(doc_id, page_id_or_name)
        return self.create_page(doc_id, new_name, content=page_content)

    def resolve_link(self, url: str, degrade_gracefully: bool = False) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/resolveBrowserLink",
            query=self._compact_query({"url": url, "degradeGracefully": degrade_gracefully or None}),
        )

    def list_tables(
        self,
        doc_id: str,
        limit: Optional[int] = None,
        next_page_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        table_types: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/docs/{self._segment(doc_id)}/tables",
            query=self._compact_query(
                {
                    "limit": None if next_page_token else limit,
                    "pageToken": next_page_token,
                    "sortBy": sort_by,
                    "tableTypes": table_types,
                }
            ),
        )

    def get_table(
        self,
        doc_id: str,
        table_id_or_name: str,
        use_updated_table_layouts: bool = False,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}",
            query=self._compact_query({"useUpdatedTableLayouts": use_updated_table_layouts or None}),
        )

    def list_columns(
        self,
        doc_id: str,
        table_id_or_name: str,
        limit: Optional[int] = None,
        next_page_token: Optional[str] = None,
        visible_only: Optional[bool] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/columns",
            query=self._compact_query(
                {
                    "limit": None if next_page_token else limit,
                    "pageToken": next_page_token,
                    "visibleOnly": visible_only,
                }
            ),
        )

    def list_rows(
        self,
        doc_id: str,
        table_id_or_name: str,
        query: Optional[str] = None,
        sort_by: Optional[str] = None,
        use_column_names: bool = True,
        value_format: str = "rich",
        visible_only: Optional[bool] = None,
        limit: Optional[int] = None,
        next_page_token: Optional[str] = None,
        sync_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/rows",
            query=self._compact_query(
                {
                    "query": query,
                    "sortBy": sort_by,
                    "useColumnNames": use_column_names,
                    "valueFormat": value_format,
                    "visibleOnly": visible_only,
                    "limit": None if next_page_token else limit,
                    "pageToken": next_page_token,
                    "syncToken": sync_token,
                }
            ),
        )

    def get_row(
        self,
        doc_id: str,
        table_id_or_name: str,
        row_id_or_name: str,
        use_column_names: bool = True,
        value_format: str = "rich",
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/rows/{self._segment(row_id_or_name)}",
            query=self._compact_query({"useColumnNames": use_column_names, "valueFormat": value_format}),
        )

    def upsert_rows(
        self,
        doc_id: str,
        table_id_or_name: str,
        rows: list[Dict[str, Any]],
        key_columns: Optional[list[str]] = None,
        disable_parsing: bool = False,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/rows",
            query=self._compact_query({"disableParsing": disable_parsing or None}),
            body={"rows": rows, "keyColumns": key_columns},
        )

    def update_row(
        self,
        doc_id: str,
        table_id_or_name: str,
        row_id_or_name: str,
        cells: list[Dict[str, Any]],
        disable_parsing: bool = False,
    ) -> Dict[str, Any]:
        return self._request(
            "PUT",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/rows/{self._segment(row_id_or_name)}",
            query=self._compact_query({"disableParsing": disable_parsing or None}),
            body={"row": {"cells": cells}},
        )

    def delete_row(self, doc_id: str, table_id_or_name: str, row_id_or_name: str) -> Dict[str, Any]:
        return self._request(
            "DELETE",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/rows/{self._segment(row_id_or_name)}",
        )

    def delete_rows(self, doc_id: str, table_id_or_name: str, row_ids: list[str]) -> Dict[str, Any]:
        return self._request(
            "DELETE",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/rows",
            body={"rowIds": row_ids},
        )

    def push_button(
        self,
        doc_id: str,
        table_id_or_name: str,
        row_id_or_name: str,
        column_id_or_name: str,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"/docs/{self._segment(doc_id)}/tables/{self._segment(table_id_or_name)}/rows/{self._segment(row_id_or_name)}/buttons/{self._segment(column_id_or_name)}",
        )

    def _request(
        self,
        method: str,
        path: Optional[str],
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        absolute_url: Optional[str] = None,
        include_auth: bool = True,
        parse_json: bool = True,
        response_label: str = "response",
    ) -> Any:
        url = absolute_url or self._build_url(path or "", query=query)
        data = None
        headers = {"Accept": "application/json" if parse_json else "*/*"}
        attempt_count = 3 if method.upper() == "GET" else 1

        if include_auth:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=data, method=method, headers=headers)

        for attempt in range(1, attempt_count + 1):
            try:
                with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
                    payload = self._decode_body_bytes(
                        response.read(),
                        response.headers.get("Content-Encoding"),
                        response_label,
                    )
                    if not parse_json:
                        return self._decode_text(payload, response_label)
                    text_payload = self._decode_text(payload, response_label)
                    if not text_payload:
                        return {}
                    try:
                        return json.loads(text_payload)
                    except json.JSONDecodeError as exc:
                        raise CodaApiError(f"Failed to parse {response_label} as JSON.") from exc
            except HTTPError as exc:
                if self._should_retry_http_error(exc, attempt, attempt_count):
                    time.sleep(self._retry_delay(attempt))
                    continue
                raw_body = self._decode_error_body(exc.read(), exc.headers.get("Content-Encoding"))
                try:
                    details = json.loads(raw_body) if raw_body else None
                except json.JSONDecodeError:
                    details = raw_body or None

                message = "Coda API request failed"
                if isinstance(details, dict):
                    message = details.get("message") or details.get("statusMessage") or message
                elif isinstance(details, str) and details:
                    message = details

                raise CodaApiError(message=message, status_code=exc.code, details=details) from exc
            except (TimeoutError, socket.timeout) as exc:
                if attempt < attempt_count:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise CodaApiError("Timed out waiting for the Coda API response.") from exc
            except URLError as exc:
                if attempt < attempt_count:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise CodaApiError(f"Failed to reach Coda API: {exc.reason}") from exc

        raise CodaApiError("Coda API request failed after retries.")

    @staticmethod
    def _build_ssl_context() -> ssl.SSLContext:
        if os.environ.get("NODE_TLS_REJECT_UNAUTHORIZED", "0") == "0":
            return ssl._create_unverified_context()
        return ssl.create_default_context()

    def _should_retry_http_error(self, exc: HTTPError, attempt: int, attempt_count: int) -> bool:
        return exc.code in self.TRANSIENT_HTTP_STATUS_CODES and attempt < attempt_count

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return min(0.5 * attempt, 2.0)

    @staticmethod
    def _report_progress(progress_callback: Optional[Callable[[str], None]], message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    @staticmethod
    def _decode_body_bytes(payload: bytes, content_encoding: Optional[str], response_label: str) -> bytes:
        is_gzip = "gzip" in (content_encoding or "").lower() or payload.startswith(b"\x1f\x8b")
        if not is_gzip:
            return payload

        try:
            return gzip.decompress(payload)
        except (OSError, EOFError) as exc:
            raise CodaApiError(f"Failed to decompress {response_label}.") from exc

    @staticmethod
    def _decode_text(payload: bytes, response_label: str) -> str:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CodaApiError(f"Failed to decode {response_label} as UTF-8 text.") from exc

    def _decode_error_body(self, payload: bytes, content_encoding: Optional[str]) -> str:
        if not payload:
            return ""
        try:
            decoded = self._decode_body_bytes(payload, content_encoding, "error response body")
        except CodaApiError:
            decoded = payload
        return decoded.decode("utf-8", errors="replace")

    def _build_url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        base = f"{self.api_base_url}/"
        url = urljoin(base, path.lstrip("/"))
        if query:
            return f"{url}?{urlencode(query, doseq=True)}"
        return url

    @staticmethod
    def _segment(value: str) -> str:
        return quote(value, safe="")

    @staticmethod
    def _compact_query(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in payload.items() if value is not None}
