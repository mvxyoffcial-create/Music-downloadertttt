from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from config import Config

client = AsyncIOMotorClient(Config.MONGO_URI)
db = client["musicbot"]
users_col = db["users"]


async def add_user(user_id: int, first_name: str, username: str = None):
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        await users_col.insert_one({
            "user_id": user_id,
            "first_name": first_name,
            "username": username,
            "joined": datetime.utcnow()
        })


async def get_all_users():
    return await users_col.find().to_list(length=None)


async def get_user_count():
    return await users_col.count_documents({})


async def get_today_users():
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())
    return await users_col.count_documents({"joined": {"$gte": today_start}})


async def get_all_user_ids():
    users = await users_col.find({}, {"user_id": 1}).to_list(length=None)
    return [u["user_id"] for u in users]
