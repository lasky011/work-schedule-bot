import asyncio

from db import USE_POSTGRES, get_db_connection, db_placeholder


def _save_user_sync(
    user_id, name=None, notify=None, notify_time=None,
    role=None, track_hours=None, notify_hours=None, notify_hours_time=None,
    theme=None,
):
    conn = get_db_connection()
    cursor = conn.cursor()

    if USE_POSTGRES:
        updates: dict = {}
        if name is not None:
            updates["name"] = name
        if notify is not None:
            updates["notify"] = notify
        if notify_time is not None:
            updates["notify_time"] = notify_time
        if role is not None:
            updates["role"] = role
        if track_hours is not None:
            updates["track_hours"] = track_hours
        if notify_hours is not None:
            updates["notify_hours"] = notify_hours
        if notify_hours_time is not None:
            updates["notify_hours_time"] = notify_hours_time
        if theme is not None:
            updates["theme"] = theme

        if updates:
            set_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in updates)
            cols = ", ".join(["user_id"] + list(updates.keys()))
            placeholders = ", ".join(["%s"] * (1 + len(updates)))
            values = [user_id] + list(updates.values())
            cursor.execute(
                f"INSERT INTO users ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT (user_id) DO UPDATE SET {set_clause}",
                values
            )
        else:
            cursor.execute(
                "INSERT INTO users (user_id, notify) VALUES (%s, 0) "
                "ON CONFLICT (user_id) DO NOTHING",
                (user_id,)
            )
    else:
        cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        exists = cursor.fetchone()
        if not exists:
            cursor.execute(
                "INSERT INTO users (user_id, name, notify, notify_time) VALUES (?, ?, ?, ?)",
                (user_id, name, notify or 0, notify_time)
            )
        else:
            if name is not None:
                cursor.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
            if notify is not None:
                cursor.execute("UPDATE users SET notify=? WHERE user_id=?", (notify, user_id))
            if notify_time is not None:
                cursor.execute("UPDATE users SET notify_time=? WHERE user_id=?", (notify_time, user_id))
            if role is not None:
                cursor.execute("UPDATE users SET role=? WHERE user_id=?", (role, user_id))
            if track_hours is not None:
                cursor.execute("UPDATE users SET track_hours=? WHERE user_id=?", (track_hours, user_id))
            if notify_hours is not None:
                cursor.execute("UPDATE users SET notify_hours=? WHERE user_id=?", (notify_hours, user_id))
            if notify_hours_time is not None:
                cursor.execute("UPDATE users SET notify_hours_time=? WHERE user_id=?", (notify_hours_time, user_id))
            if theme is not None:
                cursor.execute("UPDATE users SET theme=? WHERE user_id=?", (theme, user_id))

    conn.commit()
    cursor.close()
    conn.close()


async def save_user(
    user_id, name=None, notify=None, notify_time=None,
    role=None, track_hours=None, notify_hours=None, notify_hours_time=None,
    theme=None,
):
    await asyncio.to_thread(
        _save_user_sync, user_id, name, notify, notify_time,
        role, track_hours, notify_hours, notify_hours_time, theme
    )


def _get_user_sync(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    ph = db_placeholder()

    cursor.execute(
        f"SELECT user_id, name, notify, notify_time, role, track_hours, notify_hours, notify_hours_time, theme FROM users WHERE user_id={ph}",
        (user_id,)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    return user


async def get_user(user_id):
    return await asyncio.to_thread(_get_user_sync, user_id)


async def get_user_name(user_id):
    user = await get_user(user_id)
    return user[1] if user and user[1] else None


def _get_notify_users_sync():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id, name, notify_time, role FROM users WHERE notify=1 AND name IS NOT NULL AND notify_time IS NOT NULL"
    )

    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return users


async def get_notify_users():
    return await asyncio.to_thread(_get_notify_users_sync)


def _get_registered_users_sync():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, name, role FROM users WHERE name IS NOT NULL AND name != ''"
    )
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users


async def get_registered_users():
    return await asyncio.to_thread(_get_registered_users_sync)
