from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

MANUAL_REPORT_BUTTON = "Daily briefing"


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MANUAL_REPORT_BUTTON)]],
        resize_keyboard=True,
    )
