from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


HEARTBEAT_S = 1800.0  # an unchanged page is re-sent (fresh clock) after this long


@dataclass
class State:
    path: Path
    pages: dict[str, dict] = field(default_factory=dict)
    last_good_text: str | None = None
    last_good_at: float | None = None

    @classmethod
    def load(cls, path: Path) -> "State":
        try:
            data = json.loads(Path(path).read_text())
            return cls(
                Path(path),
                dict(data.get("pages", {})),
                data.get("last_good_text"),
                data.get("last_good_at"),
            )
        except (FileNotFoundError, ValueError):
            return cls(Path(path))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "pages": self.pages,
                    "last_good_text": self.last_good_text,
                    "last_good_at": self.last_good_at,
                }
            )
        )
        os.replace(tmp, self.path)
