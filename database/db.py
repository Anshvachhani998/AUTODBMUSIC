import motor.motor_asyncio
from info import MONGO_URI, MONGO_NAME, MAINTENANCE_MODE
from datetime import datetime, timedelta

class Database:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        self.db = self.client[MONGO_NAME]
        self.col = self.db["dump"]

    def new_user(self, id, name):
        return {"id": int(id), "name": name}

    # ----------- Dump cache methods -------------

    async def save_dump_file_id(self, track_id: str, file_id: str):
        # Upsert kare: agar document hai to update, nahi to insert
        await self.col.update_one(
            {"track_id": track_id},
            {"$set": {"file_id": file_id}},
            upsert=True
        )

    async def get_dump_file_id(self, track_id: str):
        doc = await self.col.find_one({"track_id": track_id})
        if doc and "file_id" in doc:
            return doc["file_id"]
        return None


    async def get_all_db(self) -> int:
        """Returns total number of dump entries in the database."""
        count = await self.col.count_documents({})
        return count

    async def delete_all_dumps(self) -> int:
        """Deletes all dump entries and returns how many were deleted."""
        result = await self.col.delete_many({})
        return result.deleted_count

# create instance
db = Database()
