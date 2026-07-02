"""HTML-шаблоны сообщений Telegram."""

import html

SEP = "━━━━━━━━━━━━━━"
PARSE_MODE = "HTML"


def esc(text) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def card(title: str, body: str, footer: str = "") -> str:
    parts = [f"<b>{esc(title)}</b>", "", body]
    if footer:
        parts += ["", f"<i>{esc(footer)}</i>"]
    return "\n".join(parts)


def breadcrumb(*parts: str) -> str:
    return " › ".join(esc(p) for p in parts if p)


def context_banner(name: str, role_label: str | None = None) -> str:
    line = f"👀 Смотришь: <b>{esc(name)}</b>"
    if role_label:
        line += f" · {esc(role_label)}"
    return line


def prepend_context(context_line: str | None, body: str) -> str:
    if not context_line:
        return body
    return f"{context_line}\n\n{SEP}\n\n{body}"


def onboarding_step(step: int, total: int, text: str) -> str:
    return f"<i>Шаг {step} из {total}</i>\n\n{text}"


def money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"


def fmt_hours(h) -> str:
    h = float(h)
    return str(int(h)) if h == int(h) else str(h)


def day_schedule_card(
    date_line: str,
    name: str,
    role_label: str | None,
    working: bool,
    shift_line: str | None,
    team_section: str | None = None,
    off_section: str | None = None,
) -> str:
    status = "✅ Работаешь" if working else "🏖 Выходной"
    lines = [
        f"📅 <b>{esc(date_line)}</b>",
        "",
        f"👤 <b>{esc(name)}</b>",
    ]
    if role_label:
        lines.append(esc(role_label))
    lines.append(status)
    if shift_line:
        lines.append(f"Смена: <code>{esc(shift_line)}</code>")

    if team_section:
        lines += ["", SEP, team_section]
    if off_section:
        lines += ["", off_section]

    return "\n".join(lines)


def team_on_shift(total: int, role_blocks: list[tuple[str, list[str]]]) -> str:
    lines = [f"👥 На смене: <b>{total}</b>"]
    for role_label, people in role_blocks:
        if not people:
            continue
        lines.append("")
        lines.append(f"<b>{esc(role_label)}</b>")
        for person in people:
            lines.append(f"  • {esc(person)}")
    return "\n".join(lines)


def day_off_together(people: list[str]) -> str:
    lines = ["🏖 Вместе отдыхают:"]
    for person in people:
        lines.append(f"  • {esc(person)}")
    return "\n".join(lines)


def week_table_row(day_short: str, day_num: int, icon: str, shift_short: str, on_shift: int) -> str:
    shift_cell = shift_short if shift_short else "—"
    return f"{day_short:2} {day_num:2}  {icon}  {shift_cell:8}  ({on_shift})"


def week_pre_block(header: str, table_lines: list[str]) -> str:
    table = "\n".join(table_lines)
    return f"<b>{esc(header)}</b>\n\n<pre>{table}</pre>"


def salary_dashboard(
    period_title: str,
    schedule_shifts: int,
    schedule_hours: float,
    approx_salary: int | None,
    rate: int | None,
    track_hours: bool,
    actual_shifts: int = 0,
    actual_hours: float = 0,
    actual_salary: int | None = None,
    no_data: bool = False,
) -> str:
    lines = [f"💰 <b>{esc(period_title)}</b>", ""]

    if no_data:
        lines.append("📭 График за этот период ещё не составлен.")
        lines.append("Примерная зарплата недоступна.")
        return "\n".join(lines)

    if track_hours and (actual_shifts or actual_hours):
        sched_h = fmt_hours(schedule_hours)
        act_h = fmt_hours(actual_hours)
        row_shift = f"{'Смены:':8}{schedule_shifts:<13}{actual_shifts}"
        row_hours = f"{'Часы:':8}{sched_h:<13}{act_h}"
        table = f"{'':8}По графику    По факту\n{row_shift}\n{row_hours}"
        if approx_salary is not None and actual_salary is not None:
            table += f"\n{'₽:':8}{money(approx_salary):<13}{money(actual_salary)}"
        lines.append(f"<pre>{table}</pre>")
    else:
        lines.append(f"По графику: <b>{schedule_shifts}</b> смен · <b>{fmt_hours(schedule_hours)}</b> ч")
        if approx_salary is not None:
            lines.append("")
            lines.append(f"💰 Примерно: <b>{money(approx_salary)}</b>")
            if rate:
                lines.append(f"<i>({rate} ₽/ч × {fmt_hours(schedule_hours)} ч)</i>")
        elif rate is None:
            lines.append("")
            lines.append("⚠️ Ставка для твоей должности не указана")

    if track_hours and not (actual_shifts or actual_hours):
        lines += ["", "✅ Внесено смен: <b>0</b>", "⏱ Часов: <b>0</b>"]

    return "\n".join(lines)


def who_works_card(date_line: str, my_status_html: str, role_blocks: list[tuple[str, int, list[str]]]) -> str:
    lines = [
        f"👥 <b>{esc(date_line)}</b>",
        "",
        my_status_html,
        "",
        SEP,
    ]
    has_any = False
    for role_label, count, people in role_blocks:
        if not people:
            continue
        has_any = True
        lines.append("")
        lines.append(f"<b>{esc(role_label)}</b> ({count})")
        for person in people:
            lines.append(f"  • {esc(person)}")
    if not has_any:
        lines.append("")
        lines.append("Никто не работает.")
    return "\n".join(lines)


def compare_result(
    participants: list[tuple[str, str | None]],
    period_label: str,
    common_work: list[str],
    common_off: list[str],
) -> str:
    lines = [
        "🤝 <b>Совпадения по группе</b>",
        "",
        "<b>Участники:</b>",
    ]
    for name, role_label in participants:
        if role_label:
            lines.append(f"  • {esc(name)} ({esc(role_label)})")
        else:
            lines.append(f"  • {esc(name)}")

    lines += ["", f"📅 <b>{esc(period_label)}</b>", "", SEP, ""]

    lines.append("<b>✅ Все работают:</b>")
    if common_work:
        for item in common_work:
            lines.append(f"  • {esc(item)}")
    else:
        lines.append("  нет")

    lines += ["", "<b>🏖 Все отдыхают:</b>"]
    if common_off:
        for item in common_off:
            lines.append(f"  • {esc(item)}")
    else:
        lines.append("  нет")

    return "\n".join(lines)


def welcome_card(name_part: str, action: str) -> str:
    body = (
        "Я бот расписания — помогаю смотреть график и считать зарплату.\n\n"
        "📌 <b>Мой график</b> — сегодня, завтра, неделя\n"
        "📅 <b>Сегодня</b> — всё важное на один экран\n"
        "👀 <b>Коллеги</b> — график коллег, совпадения смен\n"
        "💰 <b>Зарплата</b> — расчёт и учёт часов\n"
        "🔔 <b>Уведомления</b> — напоминания о графике"
    )
    title = f"Привет{name_part} 👋"
    return card(title, body, action)


def today_summary_card(
    name: str,
    role_label: str | None,
    today_line: str,
    tomorrow_hint: str | None = None,
    hours_hint: str | None = None,
) -> str:
    lines = [
        "📅 <b>Сегодня</b>",
        "",
        f"👤 <b>{esc(name)}</b>",
    ]
    if role_label:
        lines.append(esc(role_label))
    lines.append("")
    lines.append(today_line)
    if tomorrow_hint:
        lines += ["", f"📆 Завтра: {tomorrow_hint}"]
    if hours_hint:
        lines += ["", hours_hint]
    return "\n".join(lines)


def range_schedule_header(name: str, role_label: str | None) -> str:
    lines = [f"📋 <b>{esc(name)}</b>"]
    if role_label:
        lines.append(esc(role_label))
    return "\n".join(lines) + "\n"


def range_schedule_day(date_line: str, shift_text: str) -> str:
    return f"<b>{esc(date_line)}</b> — {esc(shift_text)}"


def empty_state(icon: str, title: str, hint: str = "") -> str:
    text = f"{icon} <b>{esc(title)}</b>"
    if hint:
        text += f"\n{esc(hint)}"
    return text
