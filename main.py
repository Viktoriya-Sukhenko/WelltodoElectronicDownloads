import os
import json
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.filters.callback_data import CallbackData
from aiogram.client.default import DefaultBotProperties
from threading import Thread

# 🔥 Отримання змінних середовища з Secrets
TOKEN = os.getenv("BOT_TOKEN")  # Читаємо токен з секретів Replit
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # ID адміна також беремо з Secrets

# 🔥 Ініціалізація Firebase через секрети (замість JSON-файлу)
firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
cred_dict = json.loads(
    firebase_credentials_json)  # Перетворюємо JSON у словник
cred = credentials.Certificate(cred_dict)  # Передаємо словник у Firebase SDK

firebase_admin.initialize_app(cred)
db = firestore.client()

# 🔥 Ініціалізація Telegram-бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

# 📌 **Головне меню**
main_menu = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Меню")]],
                                resize_keyboard=True)


# 📌 **CallbackData для кнопок**
class SiteCallback(CallbackData, prefix="site"):
    site: str


class RequestTypeCallback(CallbackData, prefix="request_type"):
    site: str
    request_type: str  # phone | chat


class RequestStatusCallback(CallbackData, prefix="request_status"):
    site: str
    request_type: str  # phone | chat
    status: str  # new | done


class RequestActionCallback(CallbackData, prefix="act"):
    rid: str
    s: str
    t: str
    a: str


# 📌 **Отримання списку сайтів**
def get_sites():
    requests_ref = db.collection("requests")
    docs = requests_ref.stream()
    return list({doc.to_dict().get("site", "Невідомий сайт") for doc in docs})


# 📌 **Отримання заявок для сайту**
def get_requests_by_site(site, request_type, status):
    requests_ref = db.collection("requests")
    query = requests_ref.where("site", "==", site)

    if status:
        query = query.where("status", "==", status)

    requests = []
    for doc in query.stream():
        data = doc.to_dict()
        data['id'] = doc.id

        # Фильтрация по типу заявки в Python
        if request_type == "phone":
            # Для звонков: есть телефон, а social равен "не вказано"
            if data.get("phone") and data.get("social") == "не вказано":
                requests.append(data)
        elif request_type == "chat":
            # Для чатов: есть телефон и social не равен "не вказано"
            if data.get("phone") and data.get("social") != "не вказано":
                requests.append(data)

    return requests


# 📌 **Команда /start**
@router.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "🔹 Вітаю! Я бот для керування заявками.\n\nℹ Натисніть 📋 Меню, щоб переглянути заявки.",
        reply_markup=main_menu)


# 📌 **Меню (список сайтів)**
@router.message(F.text.casefold() == "📋 меню")
async def menu(message: Message):
    sites = get_sites()
    if not sites:
        await message.answer("⚠️ Жоден сайт ще не надсилав заявки.")
        return

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=site,
                                 callback_data=SiteCallback(site=site).pack())
        ] for site in sites] +
        [[InlineKeyboardButton(text="⬅ Назад", callback_data="menu")]])
    await message.answer("📌 Оберіть сайт, щоб переглянути заявки:",
                         reply_markup=markup)


# 📌 **Обработка выбора типа заявок**
@router.callback_query(RequestTypeCallback.filter())
async def show_request_type_options(callback: CallbackQuery,
                                    callback_data: RequestTypeCallback):
    site = callback_data.site
    request_type = callback_data.request_type

    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🟡 Новые заявки",
                callback_data=RequestStatusCallback(
                    site=site, request_type=request_type, status="new").pack())
        ],
                         [
                             InlineKeyboardButton(
                                 text="✅ Выполненные заявки",
                                 callback_data=RequestStatusCallback(
                                     site=site,
                                     request_type=request_type,
                                     status="done").pack())
                         ],
                         [
                             InlineKeyboardButton(text="⬅ Назад",
                                                  callback_data=SiteCallback(
                                                      site=site).pack())
                         ]])

    type_text = "📞 Заявки на звонок" if request_type == "phone" else "💬 Заявки из чата"
    await callback.message.edit_text(f"📌 <b>{site}</b>\n{type_text}:",
                                     reply_markup=markup)


# 📌 **Обработка кнопки "Назад" в главном меню**
@router.callback_query(F.data == "menu")
async def back_to_menu(callback: CallbackQuery):
    sites = get_sites()
    if not sites:
        await callback.message.edit_text("⚠️ Жоден сайт ще не надсилав заявки."
                                         )
        return

    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=site,
                             callback_data=SiteCallback(site=site).pack())
    ] for site in sites])
    await callback.message.edit_text("📌 Оберіть сайт, щоб переглянути заявки:",
                                     reply_markup=markup)


# 📌 **Відображення заявок**
@router.callback_query(RequestStatusCallback.filter())
async def show_requests(callback: CallbackQuery,
                        callback_data: RequestStatusCallback):
    site = callback_data.site
    request_type = callback_data.request_type
    status = callback_data.status

    requests = get_requests_by_site(site, request_type, status)

    if not requests:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="⬅ Назад",
                callback_data=RequestTypeCallback(
                    site=site, request_type=request_type).pack())
        ]])
        await callback.message.edit_text(
            f"⚠️ На сайті {site} немає {'виконаних' if status == 'done' else 'нових'} заявок.",
            reply_markup=markup)
        return

    # Сначала отправляем сообщение о списке заявок
    await callback.message.edit_text(f"📋 Список заявок для сайту {site}:")

    # Затем отправляем каждую заявку отдельным сообщением
    for req in requests:
        await send_request_card(callback.message, req, site, request_type)

    # В конце отправляем кнопку "Назад"
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅ Назад",
                             callback_data=RequestTypeCallback(
                                 site=site, request_type=request_type).pack())
    ]])
    await callback.message.answer("📌 Оберіть дію:", reply_markup=markup)


# 📌 **Відправка заявки у вигляді карточки**
async def send_request_card(message, req, site, request_type):
    # Формируем текст в зависимости от типа заявки
    text = f"📌 <b>Заявка</b>\n🌍 <b>Сайт:</b> {req['site']}\n"

    if request_type == "phone":
        text += f"📞 <b>Телефон:</b> {req.get('phone', 'Не вказано')}\n"
    else:  # chat
        text += (
            f"📞 <b>Телефон:</b> {req.get('phone', 'Не вказано')}\n"
            f"🔗 <b>{req.get('social', 'Соцмережа')}:</b> {req.get('nickname', 'Не вказано')}\n"
        )

    text += f"🟢 <b>Статус:</b> {'✅ Виконано' if req.get('status') == 'done' else '🟡 Не виконано'}"

    buttons = []
    if req.get('status') != 'done':
        buttons.append([
            InlineKeyboardButton(text="✅ Виконано",
                                 callback_data=RequestActionCallback(
                                     rid=req['id'],
                                     s=site,
                                     t=request_type,
                                     a="done").pack())
        ])

    buttons.append([
        InlineKeyboardButton(text="🗑 Видалити",
                             callback_data=RequestActionCallback(
                                 rid=req['id'],
                                 s=site,
                                 t=request_type,
                                 a="del").pack())
    ])

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await bot.send_message(message.chat.id, text, reply_markup=markup)


# 📌 **Обробка дій із заявками**
@router.callback_query(RequestActionCallback.filter())
async def handle_request_action(callback: CallbackQuery,
                                callback_data: RequestActionCallback):
    request_ref = db.collection("requests").document(callback_data.rid)

    if callback_data.a == "done":
        request_ref.update({"status": "done"})
        await callback.answer("✅ Заявка позначена як виконана.")
    elif callback_data.a == "del":
        request_ref.delete()
        await callback.answer("🗑 Заявка видалена.")

    await show_requests(
        callback,
        RequestStatusCallback(site=callback_data.s,
                              request_type=callback_data.t,
                              status="new"))


# 📌 **Обработка выбора сайта**
@router.callback_query(SiteCallback.filter())
async def show_site_options(callback: CallbackQuery,
                            callback_data: SiteCallback):
    site = callback_data.site
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📞 Заявки на звонок",
                                 callback_data=RequestTypeCallback(
                                     site=site, request_type="phone").pack())
        ],
        [
            InlineKeyboardButton(text="💬 Заявки из чата",
                                 callback_data=RequestTypeCallback(
                                     site=site, request_type="chat").pack())
        ], [InlineKeyboardButton(text="⬅ Назад", callback_data="menu")]
    ])
    await callback.message.edit_text(f"📌 <b>{site}</b>\nОберіть тип заявок:",
                                     reply_markup=markup)


# 📌 **Запуск бота**
async def main():
    print("🔄 Запуск бота...")
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__"
