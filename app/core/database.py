import motor.motor_asyncio
from pymongo.server_api import ServerApi
from app.core.config import settings
import certifi


client: motor.motor_asyncio.AsyncIOMotorClient = None
db = 'agraound-nda'


async def connect_db():
    global client, db
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URI,
        server_api=ServerApi("1"),
        tlsCAFile=certifi.where(),
        #tls=True,
        #tlsAllowInvalidCertificates=False,
    )
    try:
        await client.admin.command("ping")
        print(f"[DB] Connected to MongoDB Atlas — database: {settings.MONGODB_DB}")
    except Exception as e:
        print(f"[DB] Connection failed: {e}")
        # No hacer raise aquí — permite que el servidor arranque igual
    db = client[settings.MONGODB_DB]


async def close_db():
    global client
    if client:
        client.close()
        print("[DB] MongoDB connection closed")


def get_db():
    return db
