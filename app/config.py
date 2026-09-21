from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SLOTS = "09:00,12:00,15:00,18:00,22:00"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    JWT_SECRET: str
    APP_USERNAME: str
    APP_PASSWORD_HASH: str
    CORS_ORIGINS: str = ""
    PORT: int = 8000

    # --- Web Push (daily word notifications) ---------------------------------
    # Generate the key pair once with scripts/generate_vapid_keys.py. With the
    # keys unset the notification endpoints still answer, but report that push
    # is disabled instead of failing at send time.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:admin@example.com"

    # Wall-clock times, in NOTIFY_TIMEZONE, at which a new word is pushed.
    NOTIFY_SLOTS: str = DEFAULT_SLOTS
    NOTIFY_TIMEZONE: str = "Europe/Brussels"
    # How late a slot may still be delivered. The dispatcher is expected to run
    # hourly; a slot missed because of a redeploy or a slow cron still goes out
    # on the next run, but a slot missed by more than this is dropped rather
    # than delivered at a useless hour.
    NOTIFY_CATCHUP_MINUTES: int = 90
    # A word pushed within this many days is not picked again while untouched
    # words remain.
    SPOTLIGHT_COOLDOWN_DAYS: int = 30
    # Used to build the deep link a notification opens.
    FRONTEND_URL: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def push_enabled(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY and self.VAPID_PRIVATE_KEY)

    @property
    def notify_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.NOTIFY_TIMEZONE)
        except ZoneInfoNotFoundError:
            raise ValueError(f"NOTIFY_TIMEZONE '{self.NOTIFY_TIMEZONE}' is not a known IANA zone") from None

    @property
    def notify_slots(self) -> list[time]:
        """Parsed HH:MM slots, sorted and de-duplicated."""
        slots: set[time] = set()
        for raw in self.NOTIFY_SLOTS.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                hour_str, minute_str = raw.split(":")
                slots.add(time(int(hour_str), int(minute_str)))
            except ValueError:
                raise ValueError(f"NOTIFY_SLOTS entry '{raw}' is not HH:MM") from None
        return sorted(slots)


settings = Settings()
