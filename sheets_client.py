import asyncio
from io import StringIO

import pandas as pd
import requests

from app_config import now_local
from app_config import SHEET_ID


def build_csv_url(gid):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"


cached_df: dict = {}
cached_time: dict = {}
cache_locks: dict = {}


def clear_sheet_cache():
    """Сброс in-memory кэша Google Sheets."""
    cached_df.clear()
    cached_time.clear()
    cache_locks.clear()


async def download_sheet(gid):
    def sync():
        url = build_csv_url(gid)
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            return pd.read_csv(StringIO(r.text), header=None)
        except requests.exceptions.Timeout:
            raise ConnectionError("⏱ Google Sheets не отвечает (таймаут). Попробуй позже.")
        except requests.exceptions.ConnectionError:
            raise ConnectionError("📡 Нет соединения с Google Sheets. Проверь интернет.")
        except requests.exceptions.HTTPError as e:
            raise ConnectionError(f"❌ Ошибка доступа к таблице: {e}. Возможно таблица закрыта.")
        except Exception as e:
            raise ConnectionError(f"❌ Не удалось загрузить график: {e}")

    return await asyncio.to_thread(sync)
