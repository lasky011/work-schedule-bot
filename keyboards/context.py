MONTHS = None
MONTHS_NOM = None
RU_HOLIDAYS = None


def configure_keyboard_context(months, months_nom, ru_holidays):
    global MONTHS, MONTHS_NOM, RU_HOLIDAYS
    MONTHS = months
    MONTHS_NOM = months_nom
    RU_HOLIDAYS = ru_holidays
