import asyncio
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from telethon import TelegramClient
from telethon.errors import ChatForwardsRestrictedError

API_ID = 32374871
API_HASH = "88bae070f4b4fb8f348eb6a16e8879d2"
SESSION_PATH = os.path.join(os.path.dirname(__file__), "user_session")

SOURCE_CHANNEL = -1002359099671
TARGET_CHANNEL = -1004477353424

async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    
    # Find a video message from source
    target_msg = None
    async for m in client.iter_messages(SOURCE_CHANNEL, limit=20):
        if m.video:
            target_msg = m
            break
            
    if not target_msg:
        print("No video found in recent messages")
        return
        
    print(f"Testing with message #{target_msg.id}: size={round(target_msg.video.size/(1024*1024))}MB")
    print(f"Caption: {target_msg.text}")
    
    # Attempt 1: direct forward (expected to fail due to noforwards)
    print("\nAttempt 1: client.forward_messages...")
    try:
        await client.forward_messages(TARGET_CHANNEL, target_msg)
        print("Attempt 1 SUCCESS (forward worked!)")
    except ChatForwardsRestrictedError:
        print("Attempt 1 FAILED as expected: ChatForwardsRestrictedError")
    except Exception as e:
        print(f"Attempt 1 FAILED: {e}")

    # Attempt 2: send_file with message.media
    print("\nAttempt 2: client.send_file(TARGET_CHANNEL, target_msg.media)...")
    try:
        await client.send_file(TARGET_CHANNEL, target_msg.media, caption=target_msg.text)
        print("Attempt 2 SUCCESS (media reference sent!)")
    except Exception as e:
        print(f"Attempt 2 FAILED: {e}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
