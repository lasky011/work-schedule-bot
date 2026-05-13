from pathlib import Path

p = Path("bot.py")
text = p.read_text()

old = '''cached_df = None
cached_time = None
cache_lock = asyncio.Lock()


async def load_full_sheet():
    global cached_df
    global cached_time

    async with cache_lock:
        now = now_local()

        if cached_df is not None and cached_time is not None:
            age = (now - cached_time).total_seconds()

            if age < 60:
                return cached_df

        df1 = await download_sheet(GID_FIRST)
        df2 = await download_sheet(GID_SECOND)

        df = pd.concat([df1, df2], ignore_index=True)

        cached_df = df
        cached_time = now

        return df


def get_day_column(df, day):
    target = str(day)

    for i in range(len(df)):
        row = df.iloc[i].fillna("").astype(str).tolist()

        for col_index, value in enumerate(row):
            if str(value).strip() == target:
                return col_index

    return None


async def find_row(name):
    df = await load_full_sheet()

    role = None

    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()

        if first in ROLES:
            role = first
            continue

        row = df.iloc[i].fillna("").astype(str).tolist()

        row_text = " ".join(row).lower()

        if name.lower() in row_text:
            return row, role

    return None, None


async def get_day_value(row, day):
    df = await load_full_sheet()

    col = get_day_column(df, day)

    if col is None:
        return ""

    if col >= len(row):
        return ""

    return row[col]
'''

new = '''cached_sheets = {}
cached_time = None
cache_lock = asyncio.Lock()


def get_sheet_gid_for_day(day: int):
    if day <= 15:
        return GID_FIRST

    return GID_SECOND


async def load_sheet(day):
    global cached_sheets
    global cached_time

    gid = get_sheet_gid_for_day(day)

    async with cache_lock:
        now = now_local()

        if (
            gid in cached_sheets
            and cached_time
            and (now - cached_time).total_seconds() < 60
        ):
            return cached_sheets[gid]

        df = await download_sheet(gid)

        cached_sheets[gid] = df
        cached_time = now

        return df


def get_day_column(df, day):
    target = str(day)

    for row_index in range(min(10, len(df))):
        row = df.iloc[row_index].fillna("").astype(str).tolist()

        for col_index, value in enumerate(row):
            if value.strip() == target:
                return col_index

    return None


async def find_row(name, day):
    df = await load_sheet(day)

    role = None

    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()

        if first in ROLES:
            role = first
            continue

        row = df.iloc[i].fillna("").astype(str).tolist()

        row_text = " ".join(row).lower()

        if name.lower() in row_text:
            return row, role

    return None, None


async def get_day_value(row, day):
    df = await load_sheet(day)

    col = get_day_column(df, day)

    if col is None:
        return ""

    if col >= len(row):
        return ""

    return row[col]
'''

text = text.replace(old, new)

text = text.replace(
    "find_row(name)",
    "find_row(name, day)"
)

text = text.replace(
    "await load_full_sheet()",
    "await load_sheet(now_local().day)"
)

p.write_text(text)

print("✅ dual-sheet logic fixed")
