import motor.motor_asyncio
from pymongo.server_api import ServerApi
from app.core.config import settings
import certifi

client = None
db = None


async def connect_db():
    global client, db

    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URI,
        server_api=ServerApi("1"),
        tls=True,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=5000,
    )

    try:
        await client.admin.command("ping")
        print(f"[DB] Connected — db: {settings.MONGODB_DB}")
    except Exception as e:
        print(f"[DB] Connection failed: {e}")

    db = client[settings.MONGODB_DB]


async def close_db():
    global client
    if client:
        client.close()
        print("[DB] MongoDB connection closed")


def get_db():
    return db


async def close_db():
    global client
    if client:
        client.close()
        print("[DB] MongoDB connection closed")


def get_db():
    return db
