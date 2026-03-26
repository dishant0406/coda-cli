from __future__ import annotations

import json
import os
import ssl
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
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
    def __init__(
        self,
        api_key: str,
        api_base_url: str = DEFAULT_API_BASE_URL,
        timeout: float = 30.0,
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

    def get_page_content(self, doc_id: str, page_id_or_name: str) -> str:
        export_job = self._request(
            "POST",
            f"/docs/{self._segment(doc_id)}/pages/{self._segment(page_id_or_name)}/export",
            body={"outputFormat": "markdown"},
        )

        request_id = export_job.get("id")
        if not request_id:
            raise CodaApiError("Page export did not return a request id")

        download_link = None
        for _ in range(self.export_max_attempts):
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

        return self._request("GET", None, absolute_url=download_link, include_auth=False, parse_json=False)

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
    ) -> Any:
        url = absolute_url or self._build_url(path or "", query=query)
        data = None
        headers = {"Accept": "application/json"}

        if include_auth:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=data, method=method, headers=headers)

        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
                payload = response.read().decode("utf-8")
                if not parse_json:
                    return payload
                if not payload:
                    return {}
                return json.loads(payload)
        except HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
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
        except URLError as exc:
            raise CodaApiError(f"Failed to reach Coda API: {exc.reason}") from exc

    @staticmethod
    def _build_ssl_context() -> ssl.SSLContext:
        if os.environ.get("NODE_TLS_REJECT_UNAUTHORIZED", "0") == "0":
            return ssl._create_unverified_context()
        return ssl.create_default_context()

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
