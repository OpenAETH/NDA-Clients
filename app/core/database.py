import motor.motor_asyncio
from pymongo.server_api import ServerApi
from app.core.config import settings
import certifi

client = None
db = None


import ssl

async def connect_db():
    global client, db
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URI,
        server_api=ServerApi("1"),
        tls=True,
        tlsAllowInvalidCertificates=False,
        tlsAllowInvalidHostnames=False,
        tlsCAFile=None,  # Usar el store del sistema
        retryWrites=True,
        retryReads=True,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000,
        # 🔥 CRÍTICO: forzar TLS 1.2+
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    )


async def close_db():
    global client
    if client:
        client.close()
        print("[DB] MongoDB connection closed")


def get_db():
    return db
