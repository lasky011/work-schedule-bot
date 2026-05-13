from pathlib import Path

p = Path("bot.py")
text = p.read_text()

text = text.replace(
'''SHEET_ID = "1bRuO870pDBf6O-kXJ1O342SmxmjZgpsiacM2aPOJm9Y"
GID = "1467004546"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"''',
'''SHEET_ID = "1bRuO870pDBf6O-kXJ1O342SmxmjZgpsiacM2aPOJm9Y"

# Лист 1-15
GID_FIRST = "1690889478"

# Лист 16-31
GID_SECOND = "1467004546"


def get_gid_by_day(day):
    if day <= 15:
        return GID_FIRST

    return GID_SECOND


def build_csv_url(gid):
    return (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv&gid={gid}"
    )'''
)

text = text.replace(
'''cached_df = None
cached_time = None
cache_lock = asyncio.Lock()''',
'''cached_df = {}
cached_time = {}
cache_lock = asyncio.Lock()'''
)

text = text.replace(
'''async def download_sheet():
    def sync():
        r = requests.get(CSV_URL, timeout=10)
        r.raise_for_status()
        r.encoding = "utf-8"
        return pd.read_csv(StringIO(r.text), header=None)

    return await asyncio.to_thread(sync)''',
'''async def download_sheet(day):
    gid = get_gid_by_day(day)
    url = build_csv_url(gid)

    def sync():
        r = requests.get(url, timeout=10)

        r.raise_for_status()
        r.encoding = "utf-8"

        return pd.read_csv(StringIO(r.text), header=None)

    return await asyncio.to_thread(sync)'''
)

text = text.replace(
'''async def load_sheet():
    global cached_df, cached_time

    async with cache_lock:
        now = now_local()

        if cached_df is not None and cached_time is not None:
            if (now - cached_time).total_seconds() < 60:
                return cached_df

        cached_df = await download_sheet()
        cached_time = now
        return cached_df''',
'''async def load_sheet(day):
    async with cache_lock:
        now = now_local()

        gid = get_gid_by_day(day)

        if gid in cached_df and gid in cached_time:
            age = (now - cached_time[gid]).total_seconds()

            if age < 60:
                return cached_df[gid]

        df = await download_sheet(day)

        cached_df[gid] = df
        cached_time[gid] = now

        return df'''
)

text = text.replace(
'''def get_day_column(df, day):
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()

        if first in ROLES:
            row = df.iloc[i].fillna("").astype(str).tolist()

            for col_index, value in enumerate(row):
                if str(value).strip() == str(day):
                    return col_index

    return None''',
'''def get_day_column(df, day):
    target = str(day)

    for i in range(len(df)):
        row = df.iloc[i].fillna("").astype(str).tolist()

        for col_index, value in enumerate(row):
            value = str(value).strip()

            if value == target:
                return col_index

    return None'''
)

text = text.replace(
'df = await load_sheet()',
'df = await load_sheet(day)'
)

text = text.replace(
'await load_sheet()',
'await load_sheet(now_local().day)'
)

p.write_text(text)

print("Готово. bot.py обновлён под 2 листа.")
