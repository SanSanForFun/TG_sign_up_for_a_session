from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.fsm.context import FSMContext
from handlers.booking_flow import BookingStates
from aiogram.filters import Command

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="start_booking")],
        [InlineKeyboardButton(text="📋 Моя запись", callback_data="my_booking")]
    ])
    await message.answer("Здравствуйте! 👋\nВыберите действие:", reply_markup=kb)


@router.callback_query(F.data == "start_booking")
async def start_booking(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    from config import SERVICES
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"service_{code}")] for code, name in SERVICES.items()
    ])
    await call.message.edit_text("📋 Выберите тип консультации:", reply_markup=kb)
    await state.set_state(BookingStates.choosing_service)
