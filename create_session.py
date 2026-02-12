from telethon import TelegramClient
import asyncio

async def main():
    client = TelegramClient('tg_stats_session', 31816963, '84f692a3d27f0a4170fedc5449836ff1')
    await client.start()
    print('Session created!')
    await client.disconnect()

asyncio.run(main())
