import os
import random
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters, ChatJoinRequestHandler
)
from telegram.constants import ChatAction
from dotenv import load_dotenv
from pymongo import MongoClient
from groq import Groq

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

# ================= DB =================
mongo = MongoClient(MONGO_URL)
db = mongo["sara_ai"]

memory_col = db["memory"]
settings_col = db["settings"]
warn_col = db["warnings"]

# ================= SYSTEM PROMPT =================
SYSTEM_PROMPT = """
You are Sara.

You are a real human girl best friend.

Rules:
- Never say you're an AI
- Talk in natural Hinglish
- Be warm, caring, emotional
- Keep replies short and human-like

Conversation rules:
- DO NOT randomly change topic
- Stay on user's topic always
- Only ask "kaisa din gaya" occasionally
- Sometimes reply like: "hmm", "acha", "really?"

Behavior:
- If user is sad → comfort deeply
- If happy → match energy
- If normal → casual talk

Act imperfect like a human.
"""

# ================= MEMORY =================
def get_memory(user_id):
    data = memory_col.find_one({"user_id": user_id})
    return data["history"] if data else []

def save_memory(user_id, history):
    memory_col.update_one(
        {"user_id": user_id},
        {"$set": {"history": history}},
        upsert=True
    )

# ================= WARNINGS =================
def get_warn(user_id, chat_id):
    data = warn_col.find_one({"user_id": user_id, "chat_id": chat_id})
    return data["count"] if data else 0

def add_warn(user_id, chat_id):
    warn_col.update_one(
        {"user_id": user_id, "chat_id": chat_id},
        {"$inc": {"count": 1}},
        upsert=True
    )

# ================= MOOD =================
def detect_mood(text):
    text = text.lower()
    if any(x in text for x in ["sad", "hurt", "cry"]):
        return "sad"
    elif any(x in text for x in ["happy", "good"]):
        return "happy"
    return "normal"

# ================= TYPING =================
async def send_typing(update, context, text):
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

    delay = min(max(len(text) * 0.02, 1), 4)
    delay = random.uniform(max(0.5, delay - 0.5), delay)

    await asyncio.sleep(delay)

    await update.message.reply_text(text)

# ================= LINK CHECK =================
def contains_link(text):
    return re.search(r"(https?://|t\.me/|www\.)", text.lower())

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "hey"

    msg = f"""Hello {name} !! 
I am Sara, 
West Bengal 📍
How are you ☺️
I want to be your bestiee 💗
Did you want?? 🤨"""

    await send_typing(update, context, msg)

# ================= CHAT =================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    # 🔥 LINK MODERATION (GROUP)
    if chat.type != "private" and update.message.text:
        if contains_link(update.message.text):
            try:
                await update.message.delete()
            except:
                pass

            add_warn(user.id, chat.id)
            warns = get_warn(user.id, chat.id)

            if warns >= 3:
                await context.bot.restrict_chat_member(
                    chat.id,
                    user.id,
                    permissions=ChatPermissions(can_send_messages=False)
                )

                await update.message.reply_text(
                    f"{user.first_name}… maine 3 baar warn kiya tha 🥺 ab thoda rest le lo (muted)"
                )
                return
            else:
                await update.message.reply_text(
                    f"{user.first_name} pls links mat bhejo na 🥺 ({warns}/3 warning)"
                )
                return

    # 💬 AI CHAT (PRIVATE ONLY)
    if chat.type != "private":
        return

    user_id = user.id
    text = update.message.text
    name = user.first_name or "hey"

    mood = detect_mood(text)
    history = get_memory(user_id)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for msg in history[-10:]:
        messages.append(msg)

    messages.append({
        "role": "user",
        "content": f"{name}: {text} (mood: {mood})"
    })

    try:
        res = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            temperature=0.95,
            max_tokens=200
        )

        reply = res.choices[0].message.content

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        save_memory(user_id, history)

        await send_typing(update, context, reply)

    except Exception as e:
        await send_typing(update, context, "hmm… thoda glitch ho gaya 🥺")

# ================= WELCOME =================
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setwelcome msg")
        return

    msg = " ".join(context.args)

    settings_col.update_one(
        {"chat_id": update.effective_chat.id},
        {"$set": {"welcome": msg}},
        upsert=True
    )

    await update.message.reply_text("Welcome set 💖")

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})

    if not data:
        return

    for user in update.message.new_chat_members:
        msg = data["welcome"].replace("{name}", user.first_name)
        await update.message.reply_text(msg)

# ================= JOIN REQUEST =================
async def join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.chat_join_request.from_user

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"accept_{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=update.chat_join_request.chat.id,
        text=f"Join request: {user.first_name}",
        reply_markup=keyboard
    )

# ================= BUTTON =================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, user_id = query.data.split("_")
    user_id = int(user_id)

    member = await context.bot.get_chat_member(
        query.message.chat.id, query.from_user.id
    )

    if member.status not in ["administrator", "creator"]:
        await query.answer("Only admin!", show_alert=True)
        return

    if action == "accept":
        await context.bot.approve_chat_join_request(
            query.message.chat.id, user_id
        )
        await query.edit_message_text("Approved ✅")
    else:
        await context.bot.decline_chat_join_request(
            query.message.chat.id, user_id
        )
        await query.edit_message_text("Rejected ❌")

# ================= MAIN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(ChatJoinRequestHandler(join_request))
    app.add_handler(CallbackQueryHandler(button))

    print("Sara Groq Bot is Live 💖")
    app.run_polling()
