
import os
import asyncio
import aiohttp
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
from plugins.autodb import run_batch_from_track_ids, run_cancel_flags
from database.db import db
from info import BOT_TOKEN, OWNER_ID

run_cancel_flags = {}

 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def download_track_ids_file(file_url: str, save_path="track_ids.txt"):
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            if resp.status == 200:
                text = await resp.text()
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(text)
                logging.info(f"Track IDs file downloaded successfully to {save_path}")
                return save_path
            else:
                logging.error(f"Failed to download track IDs file, status: {resp.status}")
                return None

def read_track_ids_from_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        track_ids = [line.strip() for line in f if line.strip()]
    logging.info(f"Read {len(track_ids)} track IDs from file {file_path}")
    return track_ids


async def process_next_task(client, download_dir, bot_id: str):
    if run_cancel_flags:
        logging.info("Another task is already running, skipping new task processing.")
        return False
        
    task = await db.tasks_collection.find_one_and_update(
        {"status": {"$in": ["pending", "processing", "running"]}, "bot_id": bot_id},
        {"$set": {"status": "processing"}},
        sort=[("created_at", 1)],
        return_document=True
    )

    if not task:
        logging.info(f"No pending task found for bot_id {bot_id}.")
        return False

    logging.info(f"Found task: {task['_id']} for user  on bot {bot_id}")
    file_url = task["file_url"]
    user_id = OWNER_ID
    file_path = await download_track_ids_file(file_url, save_path=os.path.join(download_dir, f"{task['_id']}.txt"))
    if not file_path:
        logging.error("Failed to download track IDs file, marking task as failed.")
        await db.tasks_collection.update_one({"_id": task["_id"]}, {"$set": {"status": "failed"}})
        return True

    track_ids = read_track_ids_from_file(file_path)
    try:
        os.remove(file_path)
        logging.info(f"Deleted temporary file {file_path}")
    except Exception as e:
        logging.warning(f"Could not delete temporary file {file_path}: {e}")

    try:
        await run_batch_from_track_ids(client, track_ids, user_id, task["_id"])
    except Exception as e:
        logging.error(f"Error processing task {task['_id']}: {e}")
        await db.tasks_collection.update_one({"_id": task["_id"]}, {"$set": {"status": "failed", "error": str(e)}})

    return True


async def task_runner_loop(client, download_dir):
    while True:
        bot_id = BOT_TOKEN.split(":")[0]
        found = await process_next_task(client, download_dir, bot_id)
        if not found:
            logging.info("No task found, sleeping for 10 seconds...")
            await asyncio.sleep(10)
