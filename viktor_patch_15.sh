python3 - << 'PATCH'
import ast, sys

PATH = "bot.py"

def patch(code, old, new, label):
    if old not in code:
        print(f"  ⚠️  #{label}: old string not found, skipping")
        return code
    code = code.replace(old, new, 1)
    print(f"  ✅ #{label}")
    return code

def patch_all(code, old, new, label):
    if old not in code:
        print(f"  ⚠️  #{label}: old string not found, skipping")
        return code
    count = code.count(old)
    code = code.replace(old, new)
    print(f"  ✅ #{label} ({count}x)")
    return code

with open(PATH) as f:
    code = f.read()

original = code

# 1. DEPARTMENTS_FALLBACK — add Дарья to Хостес
code = patch(code,
    '"🙋 Хостес": [\n        "Татьяна",\n        "Мария",\n        "Екатерина",\n    ],',
    '"🙋 Хостес": [\n        "Татьяна",\n        "Мария",\n        "Екатерина",\n        "Дарья",\n    ],',
    "1")

# 2. State vars
code = patch(code,
    'viewing_colleague = {}',
    'viewing_colleague = {}\nviewing_colleague_role: dict[int, str | None] = {}\n_last_selected_dept: dict[int, str | None] = {}',
    "2")

# 3. reset_modes cleanup
code = patch(code,
    '    viewing_colleague.pop(user_id, None)\n    comparing_users.discard(user_id)\n    compare_selected.pop(user_id, None)',
    '    viewing_colleague.pop(user_id, None)\n    viewing_colleague_role.pop(user_id, None)\n    _last_selected_dept.pop(user_id, None)\n    comparing_users.discard(user_id)\n    compare_selected.pop(user_id, None)',
    "3")

# 4. find_row — target_role
code = patch(code,
    'async def find_row(name, day, month=None, year=None):\n',
    'async def find_row(name, day, month=None, year=None, target_role=None):\n',
    "4a")
code = patch(code,
    '        if needle and needle in " ".join(row).lower():\n            return row, role',
    '        if needle and needle in " ".join(row).lower():\n            if target_role is None or role == target_role:\n                return row, role',
    "4b")

# 5. active_role helper
code = patch(code,
    'async def active_name(user_id):\n    if user_id in viewing_colleague:\n        return viewing_colleague[user_id]\n\n    return await get_user_name(user_id)',
    'async def active_name(user_id):\n    if user_id in viewing_colleague:\n        return viewing_colleague[user_id]\n\n    return await get_user_name(user_id)\n\n\nasync def active_role(user_id):\n    """Роль активного пользователя/коллеги для find_row."""\n    if user_id in viewing_colleague:\n        return viewing_colleague_role.get(user_id)\n    user = await get_user(user_id)\n    return user[4] if user else None',
    "5")

# 6. department_selected — track dept
code = patch(code,
    'async def department_selected(message: Message):\n    user_id = message.from_user.id\n    department = message.text',
    'async def department_selected(message: Message):\n    user_id = message.from_user.id\n    department = message.text\n\n    parts = department.split(" ", 1)\n    _last_selected_dept[user_id] = parts[1] if len(parts) == 2 else department',
    "6")

# 7. own_name_selected — use _last_selected_dept
code = patch(code,
    '    # Определяем роль по имени из DEPARTMENTS\n    user_role = None\n    for dept_label, names in DEPARTMENTS.items():\n        if message.text in names:\n            parts = dept_label.split(" ", 1)\n            user_role = parts[1] if len(parts) == 2 else dept_label\n            break',
    '    user_role = _last_selected_dept.pop(user_id, None)\n    if not user_role:\n        for dept_label, names in DEPARTMENTS.items():\n            if message.text in names:\n                parts = dept_label.split(" ", 1)\n                user_role = parts[1] if len(parts) == 2 else dept_label\n                break',
    "7")

# 8. colleague_selected — save role
code = patch(code,
    '    viewing_colleague[user_id] = colleague_name\n    selecting_colleague.discard(user_id)\n\n    compare_selected[user_id] = {colleague_name}',
    '    viewing_colleague[user_id] = colleague_name\n    viewing_colleague_role[user_id] = _last_selected_dept.pop(user_id, None)\n    selecting_colleague.discard(user_id)\n\n    compare_selected[user_id] = {colleague_name}',
    "8")

# 9-12. Schedule functions — target_role passthrough
code = patch(code,
    'async def get_day_schedule(name, day, month=None, year=None):',
    'async def get_day_schedule(name, day, month=None, year=None, target_role=None):',
    "9a")
code = patch(code,
    '    row, role = await find_row(name, day, month, year)\n\n    if not row:\n        return f"Не нашёл график для: {name}"',
    '    row, role = await find_row(name, day, month, year, target_role=target_role)\n\n    if not row:\n        return f"Не нашёл график для: {name}"',
    "9b")
code = patch(code,
    'async def get_range_schedule(name, start_day, end_day, month=None, year=None):',
    'async def get_range_schedule(name, start_day, end_day, month=None, year=None, target_role=None):',
    "10a")
code = patch(code,
    '        row, role = await find_row(name, day, month, year)\n\n        if row:',
    '        row, role = await find_row(name, day, month, year, target_role=target_role)\n\n        if row:',
    "10b")
code = patch(code,
    'async def find_next_shift(name, from_day, from_month=None, from_year=None):',
    'async def find_next_shift(name, from_day, from_month=None, from_year=None, target_role=None):',
    "11a")
code = patch(code,
    '            row, _ = await find_row(name, d, m, y)\n            if not row:\n                continue\n            value = await get_day_value(row, d, m, y)\n            if is_work_shift(value):\n                return target, value',
    '            row, _ = await find_row(name, d, m, y, target_role=target_role)\n            if not row:\n                continue\n            value = await get_day_value(row, d, m, y)\n            if is_work_shift(value):\n                return target, value',
    "11b")
code = patch(code,
    'async def get_notification_text(name):',
    'async def get_notification_text(name, target_role=None):',
    "12a")
code = patch(code,
    '    if not is_day_published(today, month, year):\n        next_dt, next_value = await find_next_shift(name, today, month, year)',
    '    if not is_day_published(today, month, year):\n        next_dt, next_value = await find_next_shift(name, today, month, year, target_role=target_role)',
    "12b")
code = patch(code,
    '    row, _ = await find_row(name, today, month, year)\n    if not row:\n        return None',
    '    row, _ = await find_row(name, today, month, year, target_role=target_role)\n    if not row:\n        return None',
    "12c")
code = patch(code,
    '    next_dt, next_value = await find_next_shift(name, today, month, year)\n    common_off = await get_common_day_off_people(name, today, month, year)',
    '    next_dt, next_value = await find_next_shift(name, today, month, year, target_role=target_role)\n    common_off = await get_common_day_off_people(name, today, month, year)',
    "12d")

# 13. get_my_status_for_day — get role from DB
code = patch(code,
    '    my_name = await get_user_name(user_id)\n\n    if not my_name:\n        return "👤 Твоё имя не выбрано."\n\n    if not is_day_published(day, month, year):\n        return "👤 Твой график: график пока не составлен."\n\n    row, _ = await find_row(my_name, day, month, year)',
    '    _user = await get_user(user_id)\n    my_name = _user[1] if _user else None\n    my_role = _user[4] if _user else None\n\n    if not my_name:\n        return "👤 Твоё имя не выбрано."\n\n    if not is_day_published(day, month, year):\n        return "👤 Твой график: график пока не составлен."\n\n    row, _ = await find_row(my_name, day, month, year, target_role=my_role)',
    "13")

# 14. compare_multiple — lookup role per name
code = patch(code,
    '        for name in all_people:\n            row, _ = await find_row(name, day)\n            if not row:\n                return f"Не смог найти график для: {name}"\n            values[name] = await get_day_value(row, day)',
    '        for name in all_people:\n            _cr = None\n            for _dl, _ns in DEPARTMENTS.items():\n                if name in _ns:\n                    _p = _dl.split(" ", 1)\n                    _cr = _p[1] if len(_p) == 2 else _dl\n                    break\n            row, _ = await find_row(name, day, target_role=_cr)\n            if not row:\n                return f"Не смог найти график для: {name}"\n            values[name] = await get_day_value(row, day)',
    "14")

# 15. show_salary_stats — pass role
code = patch(code,
    '            row, _ = await find_row(name, day, month, year)\n            if row:\n                no_data = False\n                value = await get_day_value(row, day, month, year)\n                if is_work_shift(value):\n                    schedule_shifts += 1\n                    shift_type = detect_shift_type(value)\n                    dt = datetime(year, month, day)\n                    hours = get_standard_hours(shift_type, dt) or 12.0\n                    schedule_hours += hours',
    '            row, _ = await find_row(name, day, month, year, target_role=role)\n            if row:\n                no_data = False\n                value = await get_day_value(row, day, month, year)\n                if is_work_shift(value):\n                    schedule_shifts += 1\n                    shift_type = detect_shift_type(value)\n                    dt = datetime(year, month, day)\n                    hours = get_standard_hours(shift_type, dt) or 12.0\n                    schedule_hours += hours',
    "15")

# 16. process_calendar
code = patch(code,
    '    name = user[1]\n    date_str = dt.strftime("%Y-%m-%d")\n    existing = await get_shift_for_date(user_id, date_str)\n    shift_type = None\n    standard_hours = None\n\n    try:\n        row, _ = await find_row(name, dt.day, dt.month, dt.year)',
    '    name = user[1]\n    _cal_role = user[4] if len(user) > 4 else None\n    date_str = dt.strftime("%Y-%m-%d")\n    existing = await get_shift_for_date(user_id, date_str)\n    shift_type = None\n    standard_hours = None\n\n    try:\n        row, _ = await find_row(name, dt.day, dt.month, dt.year, target_role=_cal_role)',
    "16")

# 17. shift_date_selected
code = patch(code,
    '    name = user[1]\n    now = now_local()',
    '    name = user[1]\n    _sd_role = user[4] if len(user) > 4 else None\n    now = now_local()',
    "17a")
code = patch(code,
    '        row, _ = await find_row(name, dt.day, dt.month, dt.year)\n        if row:\n            value = await get_day_value(row, dt.day, dt.month, dt.year)\n            if is_work_shift(value):\n                shift_type = detect_shift_type(value)\n                standard_hours = get_standard_hours(shift_type, dt)\n    except (ValueError, ConnectionError):\n        pass\n    shift_entering[user_id] = {',
    '        row, _ = await find_row(name, dt.day, dt.month, dt.year, target_role=_sd_role)\n        if row:\n            value = await get_day_value(row, dt.day, dt.month, dt.year)\n            if is_work_shift(value):\n                shift_type = detect_shift_type(value)\n                standard_hours = get_standard_hours(shift_type, dt)\n    except (ValueError, ConnectionError):\n        pass\n    shift_entering[user_id] = {',
    "17b")

# 18. my_schedule_menu
code = patch(code,
    '    today_line = ""\n    if name:\n        now = now_local()\n        try:\n            row, _ = await find_row(name, now.day, now.month, now.year)',
    '    _ms_role = await active_role(user_id)\n    today_line = ""\n    if name:\n        now = now_local()\n        try:\n            row, _ = await find_row(name, now.day, now.month, now.year, target_role=_ms_role)',
    "18")

# 19. today
code = patch(code,
    '    await loading_answer(\n        message, "⏳ Загружаю твой график...",\n        get_day_schedule(name, now_local().day),',
    '    _t_role = await active_role(message.from_user.id)\n    await loading_answer(\n        message, "⏳ Загружаю твой график...",\n        get_day_schedule(name, now_local().day, target_role=_t_role),',
    "19")

# 20. tomorrow
code = patch(code,
    '    tomorrow_dt = now_local() + timedelta(days=1)\n    await loading_answer(\n        message, "⏳ Загружаю график на завтра...",\n        get_day_schedule(name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year),',
    '    _tm_role = await active_role(message.from_user.id)\n    tomorrow_dt = now_local() + timedelta(days=1)\n    await loading_answer(\n        message, "⏳ Загружаю график на завтра...",\n        get_day_schedule(name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year, target_role=_tm_role),',
    "20")

# 21. _show_week_schedule
code = patch(code,
    '    if not name:\n        selecting_own_name.add(user_id)\n        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())\n\n    week_days',
    '    if not name:\n        selecting_own_name.add(user_id)\n        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())\n\n    _wk_role = await active_role(user_id)\n    week_days',
    "21a")
code = patch(code,
    '            row, _ = await find_row(name, dt.day, dt.month, dt.year)\n            people_by_role = await get_people_for_day(dt.day, dt.month, dt.year)',
    '            row, _ = await find_row(name, dt.day, dt.month, dt.year, target_role=_wk_role)\n            people_by_role = await get_people_for_day(dt.day, dt.month, dt.year)',
    "21b")

# 22. week_day_detail
code = patch(code,
    '    await loading_answer(\n        message, f"⏳ Загружаю {day_label}...",\n        get_day_schedule(name, target.day, target.month, target.year),\n        reply_markup=week_kb(week_days)',
    '    _wd_role = await active_role(user_id)\n    await loading_answer(\n        message, f"⏳ Загружаю {day_label}...",\n        get_day_schedule(name, target.day, target.month, target.year, target_role=_wd_role),\n        reply_markup=week_kb(week_days)',
    "22")

# 23. full_schedule
code = patch(code,
    '    max_day = calendar.monthrange(year, month)[1]\n    await loading_answer(\n        message, "⏳ Загружаю полный график...",\n        get_range_schedule(name, 1, max_day, month, year),',
    '    _fs_role = await active_role(message.from_user.id)\n    max_day = calendar.monthrange(year, month)[1]\n    await loading_answer(\n        message, "⏳ Загружаю полный график...",\n        get_range_schedule(name, 1, max_day, month, year, target_role=_fs_role),',
    "23")

# 24. notification_loop — query + loop
code = patch(code,
    '        "SELECT user_id, name, notify_time FROM users WHERE notify=1 AND name IS NOT NULL AND notify_time IS NOT NULL"',
    '        "SELECT user_id, name, notify_time, role FROM users WHERE notify=1 AND name IS NOT NULL AND notify_time IS NOT NULL"',
    "24a")
code = patch(code,
    '        for user_id, name, notify_time in await get_notify_users():\n            if notify_time != current_time:\n                continue\n\n            key = f"{user_id}-{today_key}-{notify_time}"\n\n            if sent.get(key):\n                continue\n\n            text = await get_notification_text(name)',
    '        for _nr in await get_notify_users():\n            user_id, name, notify_time = _nr[0], _nr[1], _nr[2]\n            _nr_role = _nr[3] if len(_nr) > 3 else None\n            if notify_time != current_time:\n                continue\n\n            key = f"{user_id}-{today_key}-{notify_time}"\n\n            if sent.get(key):\n                continue\n\n            text = await get_notification_text(name, target_role=_nr_role)',
    "24b")

# 25. hours_notification_loop
code = patch(code,
    '                "SELECT user_id, name FROM users "\n                "WHERE notify_hours=1 AND name IS NOT NULL"',
    '                "SELECT user_id, name, role FROM users "\n                "WHERE notify_hours=1 AND name IS NOT NULL"',
    "25a")
code = patch(code,
    '        for user_id, name in users:\n            key = f"{user_id}-hours-{shift_key}"\n            if sent.get(key):\n                continue\n            try:\n                if not is_day_published(shift_day, shift_month, shift_year):\n                    continue\n                row, _ = await find_row(name, shift_day, shift_month, shift_year)',
    '        for _hr in users:\n            user_id, name = _hr[0], _hr[1]\n            _hr_role = _hr[2] if len(_hr) > 2 else None\n            key = f"{user_id}-hours-{shift_key}"\n            if sent.get(key):\n                continue\n            try:\n                if not is_day_published(shift_day, shift_month, shift_year):\n                    continue\n                row, _ = await find_row(name, shift_day, shift_month, shift_year, target_role=_hr_role)',
    "25b")

# 26. Clean viewing_colleague_role wherever viewing_colleague.pop
code = patch_all(code,
    'viewing_colleague.pop(user_id, None)',
    'viewing_colleague.pop(user_id, None)\n    viewing_colleague_role.pop(user_id, None)',
    "26")

if code == original:
    print("\n❌ Ничего не изменилось!")
    sys.exit(1)

try:
    ast.parse(code)
    print("\n✅ ast.parse OK")
except SyntaxError as e:
    print(f"\n❌ SyntaxError: {e}")
    sys.exit(1)

with open(PATH, "w") as f:
    f.write(code)

print("✅ Патч #15 применён")
PATCH
