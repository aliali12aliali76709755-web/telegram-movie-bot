import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
import cryptg
from telethon import TelegramClient

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
BOT_TOKEN = "8884645024:AAFgHszR26PgAWxL5TjUAc4Hbcl7-gUpM5A"

USER_SESSION = os.path.join(os.path.dirname(__file__), "user_session")
BOT_SESSION = os.path.join(os.path.dirname(__file__), "bot_session")

async def main():
    user = TelegramClient(USER_SESSION, API_ID, API_HASH)
    bot = TelegramClient(BOT_SESSION, API_ID, API_HASH)
    
    await user.connect()
    await bot.start(bot_token=BOT_TOKEN)
    
    u_me = await user.get_me()
    b_me = await bot.get_me()
    
    print(f"User Connected: {u_me.first_name} (@{u_me.username})")
    print(f"Bot Connected: {b_me.first_name} (@{b_me.username})")
    
    await user.disconnect()
    await bot.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
