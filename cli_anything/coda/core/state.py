from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_API_BASE_URL = "https://coda.io/apis/v1"


def default_session_path() -> Path:
    raw = os.environ.get("CODA_SESSION_PATH") or os.environ.get("CLI_ANYTHING_CODA_SESSION_PATH")
    if raw:
        return Path(raw).expanduser()

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "cli-anything-coda" / "session.json"

    codex_memories = Path.home() / ".codex" / "memories"
    if codex_memories.exists():
        return codex_memories / "cli-anything-coda" / "session.json"

    return Path.home() / ".local" / "state" / "cli-anything-coda" / "session.json"


@dataclass
class SessionState:
    api_base_url: str = DEFAULT_API_BASE_URL
    current_doc_id: Optional[str] = None
    current_table_id: Optional[str] = None
    current_page_id: Optional[str] = None
    last_result: Any = None
    history: list[Dict[str, Optional[str]]] = field(default_factory=list)
    future: list[Dict[str, Optional[str]]] = field(default_factory=list)

    def snapshot(self) -> Dict[str, Optional[str]]:
        return {
            "current_doc_id": self.current_doc_id,
            "current_table_id": self.current_table_id,
            "current_page_id": self.current_page_id,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_base_url": self.api_base_url,
            "current_doc_id": self.current_doc_id,
            "current_table_id": self.current_table_id,
            "current_page_id": self.current_page_id,
            "last_result": self.last_result,
            "history": list(self.history),
            "future": list(self.future),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SessionState":
        return cls(
            api_base_url=payload.get("api_base_url") or DEFAULT_API_BASE_URL,
            current_doc_id=payload.get("current_doc_id"),
            current_table_id=payload.get("current_table_id"),
            current_page_id=payload.get("current_page_id"),
            last_result=payload.get("last_result"),
            history=list(payload.get("history") or []),
            future=list(payload.get("future") or []),
        )


class SessionStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or default_session_path()).expanduser()

    def load(self) -> SessionState:
        if not self.path.exists():
            return SessionState()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Session file is not valid JSON: {self.path}") from exc

        return SessionState.from_dict(payload)

    def save(self, state: SessionState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    def mutate(self, state: SessionState, **updates: Optional[str]) -> bool:
        before = state.snapshot()
        changed = False

        for key, value in updates.items():
            if getattr(state, key) != value:
                setattr(state, key, value)
                changed = True

        if changed:
            state.history.append(before)
            state.future.clear()
            self.save(state)

        return changed

    def set_last_result(self, state: SessionState, payload: Any) -> None:
        state.last_result = payload
        self.save(state)

    def undo(self, state: SessionState) -> bool:
        if not state.history:
            return False

        current = state.snapshot()
        previous = state.history.pop()
        state.future.append(current)
        state.current_doc_id = previous.get("current_doc_id")
        state.current_table_id = previous.get("current_table_id")
        state.current_page_id = previous.get("current_page_id")
        self.save(state)
        return True

    def redo(self, state: SessionState) -> bool:
        if not state.future:
            return False

        current = state.snapshot()
        next_snapshot = state.future.pop()
        state.history.append(current)
        state.current_doc_id = next_snapshot.get("current_doc_id")
        state.current_table_id = next_snapshot.get("current_table_id")
        state.current_page_id = next_snapshot.get("current_page_id")
        self.save(state)
        return True
