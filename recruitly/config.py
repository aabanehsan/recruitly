"""App settings, read from environment variables with sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("RECRUITLY_DATA_DIR", "data")).resolve())
    org_name: str = field(default_factory=lambda: os.environ.get("RECRUITLY_ORG_NAME", "Recruitly"))
    cycle_name: str = field(default_factory=lambda: os.environ.get("RECRUITLY_CYCLE", "Fall Rush"))
    # Optional: warn when an applicant's email isn't on this domain (e.g. utexas.edu)
    email_domain: str | None = field(default_factory=lambda: os.environ.get("RECRUITLY_EMAIL_DOMAIN") or None)
    # Set to "0" to skip trying to download headshots from Google Drive links
    fetch_headshots: bool = field(default_factory=lambda: os.environ.get("RECRUITLY_FETCH_HEADSHOTS", "1") != "0")

    @property
    def db_url(self) -> str:
        return os.environ.get("RECRUITLY_DB_URL", f"sqlite:///{self.data_dir / 'recruitly.db'}")

    @property
    def headshot_dir(self) -> Path:
        return self.data_dir / "headshots"

    def ensure_dirs(self) -> None:
        self.headshot_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
