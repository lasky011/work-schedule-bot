import asyncio
import functools
import logging
import traceback
from datetime import datetime

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from message_format import PARSE_MODE

MIN_LOADING_SEC = 0.8

MONTHS = None
MONTHS_NOM = None


def configure_ui_utils(months, months_nom):
    global MONTHS, MONTHS_NOM
    MONTHS = months
    MONTHS_NOM = months_nom


def month_label(month: int) -> str:
    try:
        return MONTHS_NOM[month]
    except Exception:
        try:
            return MONTHS[month]
        except Exception:
            return str(month)


def fmt_hours(h) -> str:
    """12.0 → '12', 12.5 → '12.5'"""
    h = float(h)
    return str(int(h)) if h == int(h) else str(h)


def is_valid_time(text: str) -> bool:
    try:
        datetime.strptime(text.strip(), "%H:%M")
        return True
    except ValueError:
        return False


def with_loading(text="⏳ Загружаю..."):
    """Декоратор: показывает loading → хендлер → удаляет loading."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            event = args[0]
            if isinstance(event, CallbackQuery):
                msg_target = event.message
            else:
                msg_target = event
            loading = await msg_target.answer(text)
            t0 = asyncio.get_event_loop().time()
            try:
                return await func(*args, **kwargs)
            finally:
                elapsed = asyncio.get_event_loop().time() - t0
                if elapsed < MIN_LOADING_SEC:
                    await asyncio.sleep(MIN_LOADING_SEC - elapsed)
                try:
                    await loading.delete()
                except Exception:
                    pass
        return wrapper
    return decorator


async def loading_answer(
    message: Message,
    loading_text: str,
    coro_or_text,
    reply_markup=None,
    parse_mode: str | None = PARSE_MODE,
    inline_markup: InlineKeyboardMarkup | None = None,
):
    """Показывает loading_text, затем плавно заменяет на результат."""
    loading = await message.answer(loading_text)
    t0 = asyncio.get_event_loop().time()
    if asyncio.iscoroutine(coro_or_text):
        try:
            result = await coro_or_text
        except ConnectionError as e:
            result = str(e)
            parse_mode = None
        except ValueError as e:
            result = f"📋 {e}"
            parse_mode = None
        except Exception as e:
            logging.error(f"loading_answer: {e}\n{traceback.format_exc()}")
            result = "❌ Что-то пошло не так. Попробуй позже."
            parse_mode = None
    else:
        result = coro_or_text

    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < MIN_LOADING_SEC:
        await asyncio.sleep(MIN_LOADING_SEC - elapsed)

    send_kwargs = {}
    if parse_mode:
        send_kwargs["parse_mode"] = parse_mode

    if reply_markup or inline_markup:
        try:
            await loading.delete()
        except Exception:
            pass
        if inline_markup:
            send_kwargs["reply_markup"] = inline_markup
        elif reply_markup:
            send_kwargs["reply_markup"] = reply_markup
        await message.answer(str(result), **send_kwargs)
    else:
        try:
            await loading.edit_text(str(result), **send_kwargs)
        except Exception:
            try:
                await loading.delete()
            except Exception:
                pass
            await message.answer(str(result), **send_kwargs)


async def answer_html(
    message: Message,
    text: str,
    reply_markup: ReplyKeyboardMarkup | None = None,
    inline_markup: InlineKeyboardMarkup | None = None,
):
    kwargs = {"parse_mode": PARSE_MODE}
    if inline_markup:
        kwargs["reply_markup"] = inline_markup
    elif reply_markup:
        kwargs["reply_markup"] = reply_markup
    return await message.answer(text, **kwargs)


async def safe_schedule(coro):
    """Оборачивает вызов в try/except и возвращает текст ошибки если что-то пошло не так."""
    try:
        return await coro
    except ConnectionError as e:
        return str(e)
    except ValueError as e:
        return f"📋 {e}"
    except Exception as e:
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        return "❌ Что-то пошло не так. Попробуй позже."
