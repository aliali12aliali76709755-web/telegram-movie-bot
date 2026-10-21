import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from telethon import TelegramClient

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")
BOT_USERNAME = "zxeeabot"

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    print("1. Sending search query 'Move' to bot...")
    await client.send_message(BOT_USERNAME, "Move")
    await asyncio.sleep(2)
    
    # Read response
    bot_msg = None
    async for msg in client.iter_messages(BOT_USERNAME, limit=2):
        if not msg.out:
            bot_msg = msg
            break
            
    if bot_msg and bot_msg.buttons:
        print(f"Bot Search Result Text: {bot_msg.text}")
        print("Buttons found:")
        for row in bot_msg.buttons:
            for b in row:
                print(f"  [{b.text}] -> data: {b.data}")
                
        # Click the first series button
        print("\n2. Clicking series button...")
        await bot_msg.click(0, 0)
        await asyncio.sleep(2)
        
        # Check updated message
        updated_msg = await client.get_messages(BOT_USERNAME, ids=bot_msg.id)
        print(f"\nSeries Card Text:\n{updated_msg.text}")
        print("Season Buttons:")
        for row in updated_msg.buttons:
            for b in row:
                print(f"  [{b.text}] -> data: {b.data}")
                
        # Click Season 1
        print("\n3. Clicking Season 1 button...")
        await updated_msg.click(0, 0)
        await asyncio.sleep(2)
        
        # Check episode grid
        episodes_msg = await client.get_messages(BOT_USERNAME, ids=bot_msg.id)
        print(f"\nEpisodes Grid Text:\n{episodes_msg.text}")
        print("Episode Grid Buttons (3 per row):")
        for row in episodes_msg.buttons:
            row_str = " | ".join([f"[{b.text}]" for b in row])
            print(f"  {row_str}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
