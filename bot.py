import asyncio
import os
from datetime import date, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# ====== НАСТРОЙКИ (токен и ID берём из переменных окружения) ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # твой Telegram ID, сюда приходят заявки

SHOP_NAME = "Барбершоп «Борода»"
ADDRESS = "ул. Примерная, 10"
PHONE = "+7 900 000-00-00"
HOURS = "Ежедневно 10:00-20:00"

SERVICES = [
    ("Мужская стрижка", 1500),
    ("Стрижка + борода", 2300),
    ("Моделирование бороды", 1000),
    ("Детская стрижка", 1000),
]
TIMES = ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"]
DAYS_AHEAD = 7

# Занятые слоты хранятся в памяти (после перезапуска бота сбросятся)
BOOKED: set[tuple[str, str]] = set()

dp = Dispatcher(storage=MemoryStorage())


class Booking(StatesGroup):
    name = State()
    phone = State()


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✂️ Записаться")],
            [KeyboardButton(text="💈 Услуги и цены"), KeyboardButton(text="📍 Адрес и контакты")],
        ],
        resize_keyboard=True,
    )


def services_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{n} — {p} ₽", callback_data=f"svc:{i}")]
        for i, (n, p) in enumerate(SERVICES)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dates_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(DAYS_AHEAD):
        d = date.today() + timedelta(days=i)
        rows.append([InlineKeyboardButton(text=d.strftime("%d.%m"), callback_data=f"date:{d.isoformat()}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def times_kb(day: str) -> InlineKeyboardMarkup | None:
    free = [t for t in TIMES if (day, t) not in BOOKED]
    if not free:
        return None
    rows = [
        [InlineKeyboardButton(text=t, callback_data=f"time:{t}") for t in free[i : i + 3]]
        for i in range(0, len(free), 3)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(f"Привет! Это {SHOP_NAME}. Чем помочь?", reply_markup=main_menu())


@dp.message(F.text == "💈 Услуги и цены")
async def prices(message: Message):
    text = "\n".join(f"• {n} — {p} ₽" for n, p in SERVICES)
    await message.answer(f"Наши услуги:\n{text}")


@dp.message(F.text == "📍 Адрес и контакты")
async def contacts(message: Message):
    await message.answer(f"📍 {ADDRESS}\n🕒 {HOURS}\n📞 {PHONE}")


@dp.message(F.text == "✂️ Записаться")
async def book_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выбери услугу:", reply_markup=services_kb())


@dp.callback_query(F.data.startswith("svc:"))
async def choose_service(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[1])
    await state.update_data(service=SERVICES[idx][0])
    await call.message.edit_text("Выбери дату:", reply_markup=dates_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("date:"))
async def choose_date(call: CallbackQuery, state: FSMContext):
    day = call.data.split(":", 1)[1]
    kb = times_kb(day)
    if kb is None:
        await call.answer("На этот день всё занято, выбери другой", show_alert=True)
        return
    await state.update_data(day=day)
    await call.message.edit_text("Выбери время:", reply_markup=kb)
    await call.answer()


@dp.callback_query(F.data.startswith("time:"))
async def choose_time(call: CallbackQuery, state: FSMContext):
    time = call.data.split(":", 1)[1]
    data = await state.get_data()
    if (data["day"], time) in BOOKED:
        await call.answer("Это время уже заняли, выбери другое", show_alert=True)
        return
    await state.update_data(time=time)
    await state.set_state(Booking.name)
    await call.message.edit_text("Как тебя зовут?")
    await call.answer()


@dp.message(Booking.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Booking.phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Оставь номер телефона (кнопкой или текстом):", reply_markup=kb)


@dp.message(Booking.phone)
async def get_phone(message: Message, state: FSMContext, bot: Bot):
    phone = message.contact.phone_number if message.contact else message.text
    data = await state.get_data()
    key = (data["day"], data["time"])
    if key in BOOKED:
        await message.answer("Упс, это время только что заняли. Нажми «Записаться» и выбери другое.", reply_markup=main_menu())
        await state.clear()
        return
    BOOKED.add(key)

    day_fmt = date.fromisoformat(data["day"]).strftime("%d.%m")
    await message.answer(
        f"Готово! Ждём тебя {day_fmt} в {data['time']}.\nУслуга: {data['service']}",
        reply_markup=main_menu(),
    )
    if ADMIN_ID:
        await bot.send_message(
            ADMIN_ID,
            f"🆕 Новая запись\n{data['service']}\n{day_fmt} {data['time']}\n"
            f"Имя: {data['name']}\nТелефон: {phone}",
        )
    await state.clear()


async def main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
