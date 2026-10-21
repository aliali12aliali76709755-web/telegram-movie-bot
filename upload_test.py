import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
import cryptg
from telethon import TelegramClient

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")
TARGET_CHANNEL = -1004477353424
FILE_PATH = os.path.join(os.path.dirname(__file__), "temp", "IMG_8941.MP4")

def progress_callback(current, total):
    percent = round(current / total * 100, 1)
    mb_curr = round(current / (1024 * 1024), 1)
    mb_tot = round(total / (1024 * 1024), 1)
    print(f"Uploading: {mb_curr}/{mb_tot} MB ({percent}%)", flush=True)

async def main():
    if not os.path.exists(FILE_PATH):
        print("File does not exist!")
        return

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    print(f"Uploading {FILE_PATH} ({round(os.path.getsize(FILE_PATH)/(1024*1024), 2)} MB) with cryptg acceleration...")
    t0 = time.time()
    
    msg = await client.send_file(
        TARGET_CHANNEL,
        FILE_PATH,
        caption="🎬 تجربة أول فيديو مسحوب من القناة المقيدة",
        supports_streaming=True,
        progress_callback=progress_callback
    )
    
    elapsed = round(time.time() - t0, 1)
    print(f"\nSUCCESS! Uploaded to 'قناة افلام' as Msg #{msg.id} in {elapsed} seconds!")
    
    # Remove temp file
    os.remove(FILE_PATH)
    print("Cleaned up temp file.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
