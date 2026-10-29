from dataclasses import dataclass, field
from pathlib import Path
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
MSK = ZoneInfo('Europe/Moscow')


@dataclass(frozen=True)
class Account:
    key: str
    name: str
    token: str = field(repr=False)
    secret: str = field(default='', repr=False)


@dataclass(frozen=True)
class Config:
    telegram_token: str = field(repr=False)
    allowed: frozenset[int]
    accounts: tuple[Account, ...]
    data_dir: Path
    query_limit: int = 30
    analytics_interval: float = 21

    @classmethod
    def load(cls):
        # Deliberately do not discover the other bot's .env in the parent folder.
        load_dotenv(ROOT / '.env')
        token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        ids = os.getenv('ALLOWED_USER_IDS', '')
        try:
            allowed = frozenset(int(x.strip()) for x in ids.split(',') if x.strip())
        except ValueError:
            raise ValueError('ALLOWED_USER_IDS: нужны числовые Telegram ID через запятую') from None
        if not token or not allowed or any(x <= 0 for x in allowed):
            raise ValueError('Заполните TELEGRAM_BOT_TOKEN и ALLOWED_USER_IDS в wb_positions/.env')
        accounts = tuple(Account(str(i), os.getenv(f'WB_{i}_NAME', f'Кабинет {i}'),
                                 os.getenv(f'WB_{i}_TOKEN', '').strip(),
                                 os.getenv(f'WB_{i}_CLIENT_SECRET', '').strip()) for i in (1, 2))
        if any(not a.token for a in accounts):
            raise ValueError('Заполните WB_1_TOKEN и WB_2_TOKEN в wb_positions/.env')
        limit = int(os.getenv('WB_QUERY_LIMIT', '30'))
        interval = float(os.getenv('WB_ANALYTICS_INTERVAL', '21'))
        if limit not in (30, 100) or interval < 20:
            raise ValueError('WB_QUERY_LIMIT: 30 или 100; WB_ANALYTICS_INTERVAL: не менее 20')
        path = Path(os.getenv('POSITIONS_DATA_DIR', 'data'))
        if not path.is_absolute():
            path = ROOT / path
        return cls(token, allowed, accounts, path, limit, interval)
