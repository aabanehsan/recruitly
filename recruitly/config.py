"""App settings, read from environment variables with sensible defaults."""

from __future__ import annotations

import os
import secrets
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
    # Set to "1" when serving over HTTPS so session cookies are only sent securely
    secure_cookies: bool = field(default_factory=lambda: os.environ.get("RECRUITLY_SECURE_COOKIES", "0") == "1")
    # Set by `recruitly demo` so the login page can show the demo accounts
    demo: bool = field(default_factory=lambda: os.environ.get("RECRUITLY_DEMO", "0") == "1")

    @property
    def db_url(self) -> str:
        return os.environ.get("RECRUITLY_DB_URL", f"sqlite:///{self.data_dir / 'recruitly.db'}")

    @property
    def headshot_dir(self) -> Path:
        return self.data_dir / "headshots"

    @property
    def secret_key(self) -> str:
        """Key that signs session cookies. From RECRUITLY_SECRET_KEY, or generated once into the data folder."""
        env = os.environ.get("RECRUITLY_SECRET_KEY")
        if env:
            return env
        path = self.data_dir / "secret_key"
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover - e.g. some Windows filesystems
            pass
        return key

    def ensure_dirs(self) -> None:
        self.headshot_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
