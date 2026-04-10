import motor.motor_asyncio
from pymongo.server_api import ServerApi
from app.core.config import settings

client: motor.motor_asyncio.AsyncIOMotorClient = None
db = None


async def connect_db():
    global client, db
    # ServerApi("1") enforces MongoDB Stable API — required for Atlas
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URI,
        server_api=ServerApi("1"),
        tls=True,
        tlsAllowInvalidCertificates=False,
    )
    # Ping to verify connection before accepting traffic
    try:
        await client.admin.command("ping")
        print(f"[DB] Connected to MongoDB Atlas — database: {settings.MONGODB_DB}")
    except Exception as e:
        print(f"[DB] Connection failed: {e}")
        raise
    db = client[settings.MONGODB_DB]


async def close_db():
    global client
    if client:
        client.close()
        print("[DB] MongoDB connection closed")


def get_db():
    return db
