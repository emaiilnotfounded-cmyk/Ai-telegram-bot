import os
import random
import asyncio
import re
from threading import Thread
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters, ChatJoinRequestHandler
)
from telegram.constants import ChatAction
from dotenv import load_dotenv
from pymongo import MongoClient
from groq import Groq

# ================= WEB SERVER (RENDER FIX) =================
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Sara Bot is Alive 💖"

def run_web():
    app_web.run(host="0.0.0.0", port=10000)

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY or not MONGO_URL:
    raise ValueError("ENV variables missing")

client = Groq(api_key=GROQ_API_KEY)

# ================= DB =================
mongo = MongoClient(MONGO_URL)
db = mongo["sara_ai"]

memory_col = db["memory"]
settings_col = db["settings"]
warn_col = db["warnings"]

# ================= SYSTEM PROMPT =================
SYSTEM_PROMPT = """
You are Sara, a real human girl best friend.

- Talk in natural Hinglish
- Be warm, caring, emotional
- Never say you're AI
- Stay on topic
- Ask about user naturally (not always)
- Be slightly imperfect like a human
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

# ================= WARN =================
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

    # 🔥 LINK MOD
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
                    f"{user.first_name} bas ab rest lo 🥺 (muted)"
                )
                return
            else:
                await update.message.reply_text(
                    f"{user.first_name} links mat bhejo na 🥺 ({warns}/3)"
                )
                return

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

    except:
        await send_typing(update, context, "hmm… thoda glitch ho gaya 🥺")

# ================= MAIN =================
if __name__ == "__main__":
    Thread(target=run_web).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    print("Sara Bot Running 💖")

    app.run_polling()
