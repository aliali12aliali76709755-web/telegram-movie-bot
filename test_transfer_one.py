import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
from telethon import TelegramClient

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")

SOURCE_CHANNEL = -1002359099671
TARGET_CHANNEL = -1004477353424

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    print("Finding a suitable video to test transfer...")
    chosen_msg = None
    async for m in client.iter_messages(SOURCE_CHANNEL, limit=100):
        if m.video and m.video.size < 60 * 1024 * 1024: # less than 60MB for quick test
            chosen_msg = m
            break
            
    if not chosen_msg:
        # Find smallest video among 50 messages
        candidates = []
        async for m in client.iter_messages(SOURCE_CHANNEL, limit=50):
            if m.video:
                candidates.append((m.video.size, m))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            chosen_msg = candidates[0][1]

    if not chosen_msg:
        print("No video found to test!")
        await client.disconnect()
        return

    size_mb = round(chosen_msg.video.size / (1024 * 1024), 2)
    print(f"Selected Message #{chosen_msg.id}: Size={size_mb} MB")
    print(f"Original Caption:\n{chosen_msg.text}\n")
    
    temp_dir = os.path.join(os.path.dirname(__file__), "temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    t0 = time.time()
    print("Step 1: Downloading restricted video chunk stream...")
    file_path = await client.download_media(chosen_msg, file=temp_dir)
    print(f"Downloaded to {file_path} in {round(time.time() - t0, 1)}s")
    
    t1 = time.time()
    print("Step 2: Uploading video to 'قناة افلام'...")
    # Keep original caption in the storage channel as requested
    sent_msg = await client.send_file(
        TARGET_CHANNEL,
        file_path,
        caption=chosen_msg.text,
        supports_streaming=True
    )
    print(f"Uploaded successfully to 'قناة افلام' as Msg #{sent_msg.id} in {round(time.time() - t1, 1)}s!")
    
    # Clean up local file
    if os.path.exists(file_path):
        os.remove(file_path)
        print("Local temp file cleaned up.")
        
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
