import os
from pathlib import Path

import pytest

GOLD = Path(__file__).parent / "golden"


@pytest.fixture
def golden():
    def check(name: str, png: bytes) -> None:
        path = GOLD / name
        if os.environ.get("UPDATE_GOLDEN"):
            GOLD.mkdir(exist_ok=True)
            path.write_bytes(png)
            return
        assert path.exists(), f"missing golden {name}; run UPDATE_GOLDEN=1 pytest"
        assert path.read_bytes() == png, (
            f"{name} differs. Inspect the image, then regenerate with UPDATE_GOLDEN=1 if intended."
        )

    return check
