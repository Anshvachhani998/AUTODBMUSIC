from pyrogram import Client, filters
import os
import time
import logging 
import aiohttp
import requests
import asyncio
import subprocess
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import LOG_CHANNEL, ADMINS, BOT_TOKEN
from database.db import db

@Client.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 Hello! Bot is running successfully!")


@Client.on_message(filters.command("restart"))
async def git_pull(client, message):
    if message.from_user.id not in ADMINS:
        return await message.reply_text("🚫 **You are not authorized to use this command!**")
      
    working_directory = "/home/ubuntu/URL-UPLOADER"

    process = subprocess.Popen(
        "git pull https://github.com/Anshvachhani998/SpotifyDL",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE

    )

    stdout, stderr = process.communicate()
    output = stdout.decode().strip()
    error = stderr.decode().strip()
    cwd = os.getcwd()
    logging.info("Raw Output (stdout): %s", output)
    logging.info("Raw Error (stderr): %s", error)

    if error and "Already up to date." not in output and "FETCH_HEAD" not in error:
        await message.reply_text(f"❌ Error occurred: {os.getcwd()}\n{error}")
        logging.info(f"get dic {cwd}")
        return

    if "Already up to date." in output:
        await message.reply_text("🚀 Repository is already up to date!")
        return
      
    if any(word in output.lower() for word in [
        "updating", "changed", "insert", "delete", "merge", "fast-forward",
        "files", "create mode", "rename", "pulling"
    ]):
        await message.reply_text(f"📦 Git Pull Output:\n```\n{output}\n```")
        await message.reply_text("🔄 Git Pull successful!\n♻ Restarting bot...")

        subprocess.Popen("bash /home/ubuntu/SpotifyDL/start.sh", shell=True)
        os._exit(0)

    await message.reply_text(f"📦 Git Pull Output:\n```\n{output}\n```")





@Client.on_message(filters.command("stats"))
async def dump_stats(client, message):
    count = await db.get_all_db()
    await message.reply(f"📊 Total dump tracks in DB: **{count}**")

@Client.on_message(filters.command("delete"))
async def dump_delete(client, message):
    # Confirmation buttons
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes", callback_data="confirm_delete_dumps"),
                InlineKeyboardButton("❌ No", callback_data="cancel_delete_dumps"),
            ]
        ]
    )
    await message.reply(
        "⚠️ Are you sure you want to delete ALL dump entries?",
        reply_markup=keyboard
    )

@Client.on_callback_query(filters.regex(r"confirm_delete_dumps"))
async def confirm_delete(client, callback_query):
    deleted = await db.delete_all_dumps()
    await callback_query.message.edit_text(f"🗑️ Deleted **{deleted}** dump entries from the database.")
    await callback_query.answer()

@Client.on_callback_query(filters.regex(r"cancel_delete_dumps"))
async def cancel_delete(client, callback_query):
    await callback_query.message.edit_text("❌ Deletion cancelled.")
    await callback_query.answer()



@Client.on_message(filters.command("ip") & filters.private)
async def send_ip(client, message):
    try:
        ip = requests.get("https://ipinfo.io/ip").text.strip()
        await message.reply(f"🌐 My public IP is:\n`{ip}`")
    except Exception as e:
        await message.reply(f"❌ Failed to get IP:\n{e}")
        


# plugins/check_clients.py

from pyrogram import Client, filters
from pyrogram.types import Message
import aiohttp
import base64
import asyncio

# plugins/check_clients_spotipy.py

import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException

# Your list of (client_id, client_secret) pairs
clients = [
    ("5561376fd0234838863a8c3a6cbb0865", "fa12e995f56c48a28e28fb056e041d18"),
    ("a8c78174e7524e109d669ee67bbad3f2", "3074289c88ac4071bef5c11ca210a8e5"),
    ("d52e171b692e43f88ea267071f0e838d", "b5ab6396e98545e9bc2e023974d964cc"),
    ("3e79d9be3a9746038990b0f24b8da4ec", "e09cd70a34324eb187c039d91eec3d32"),
    ("5b44824842c544b8bf37e3de3ad3aebb", "139b46229135425f832cf85e89b8c146"),
    ("9d8d72848be94c499c41fa4212be0fc6", "d4a060bb03ce492da18ef952886ee6b4"),
    ("798cb845b47344e8821195ff0dfb9743", "ee1263d2f69e4eb59f3f0630dc33db8b"),
    ("75fc197a1b544b9f9555305e4dba6857", "ee58d745afef4c8d9e2fb0519b2346c4"),
    ("eee9c7e5d00245d793dc2befa5b52c5c", "f69875e10cc84e04a1a60c061a55012d"),
    ("b371f3149d7248f3a4fe9cb6a8678c7a", "b64961abb1b34db2bba52e2e21098796"),
    ("29bb28fe38134e1ab1a512e829e908cb", "1cf618724f244263805fe511ece20518"),
]

client_cooldowns = {}

async def check_client(cid, secret):
    now = time.time()
    cooldown_end = client_cooldowns.get(cid, 0)
    if now < cooldown_end:
        remain = int(cooldown_end - now)
        return f"⏳ `{cid[:8]}...` is on cooldown for {remain}s."

    try:
        auth = SpotifyClientCredentials(client_id=cid, client_secret=secret)
        sp = spotipy.Spotify(auth_manager=auth, retries=0)
        sp.artist_albums("7HCqGPJcQTyGJ2yqntbuyr", limit=1)  # Test request
        return f"✅ `{cid[:8]}...` is working."
    except SpotifyException as e:
        if e.http_status == 429:
            retry_after = int(e.headers.get("Retry-After", 10))
            client_cooldowns[cid] = time.time() + retry_after
            return f"⚠️ `{cid[:8]}...` rate-limited! Cooldown {retry_after}s."
        else:
            return f"❌ `{cid[:8]}...` error: {e}"
    except Exception as ex:
        return f"❌ `{cid[:8]}...` unexpected error: {ex}"

@Client.on_message(filters.command("test") & filters.private)
async def check_clients_cmd(client, message: Message):
    await message.reply("🔍 Checking all Spotify clients... Please wait.")
    results = []

    for cid, secret in clients:
        status = await check_client(cid, secret)
        results.append(status)
        await asyncio.sleep(1.5)  # Avoid hitting rate limit instantly

    await message.reply("\n".join(results))




client_cooldowns = {}


from pyrogram import Client, filters
import os

COMBINED_FILE = "combined_track_ids.txt"

# 1. Auto combine track IDs when a .txt file is sent
@Client.on_message(filters.document & filters.private)
async def auto_combine_track_ids(client, message):
    if not message.document.file_name.endswith(".txt"):
        return

    file_path = await message.download()
    added_ids = 0

    try:
        with open(file_path, "r", encoding="utf-8") as incoming_file:
            incoming_ids = [line.strip() for line in incoming_file if line.strip()]

        # Create file if not exists
        if not os.path.exists(COMBINED_FILE):
            open(COMBINED_FILE, "w", encoding="utf-8").close()

        # Append all incoming IDs without duplicate check
        with open(COMBINED_FILE, "a", encoding="utf-8") as combined_file:
            for track_id in incoming_ids:
                combined_file.write(track_id + "\n")
                added_ids += 1

        await message.reply(f"✅ `{added_ids}` track IDs added (including duplicates).")
    except Exception as e:
        await message.reply(f"❌ Error:\n`{e}`")

# 2. /clear command to wipe the combined file
@Client.on_message(filters.command("clear") & filters.private)
async def clear_combined_file(client, message):
    if os.path.exists(COMBINED_FILE):
        open(COMBINED_FILE, "w", encoding="utf-8").close()
        await message.reply("🧹 Combined track list cleared.")
    else:
        await message.reply("⚠️ No file to clear.")


# 3. Optional: Send the combined file on demand
@Client.on_message(filters.command("getfile") & filters.private)
async def send_combined_file(client, message):
    if os.path.exists(COMBINED_FILE):
        await message.reply_document(COMBINED_FILE, caption="📄 Combined Track IDs")
    else:
        await message.reply("⚠️ No combined file found yet.")


@Client.on_message(filters.command("checkall") & filters.private & filters.reply)
async def check_tracks_in_db(client, message):
    if not message.reply_to_message.document:
        await message.reply("❗ Please reply to a `.txt` file containing track IDs (one per line).")
        return

    status_msg = await message.reply("📥 Downloading file and starting processing...")

    file_path = await message.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    total_tracks = len(lines)
    new_tracks = []
    already_in_db = 0

    for idx, track_id in enumerate(lines, 1):
        try:
            exists = await db.get_dump_file_id(track_id)
            if not exists:
                new_tracks.append(track_id)
            else:
                already_in_db += 1

            if idx % 100 == 0 or idx == total_tracks:
                text = (
                    f"Processing tracks...\n"
                    f"Total tracks: {total_tracks}\n"
                    f"Checked: {idx}\n"
                    f"Already in DB: {already_in_db}\n"
                    f"New tracks to add: {len(new_tracks)}"
                )
                try:
                    await status_msg.edit(text)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                except Exception:
                    pass

        except FloodWait as e:
            await asyncio.sleep(e.x)
            continue
        except Exception as e:
            print(f"Error checking track {track_id}: {e}")
            continue

    batch_size = 10000
    batches = [new_tracks[i:i + batch_size] for i in range(0, len(new_tracks), batch_size)]

    for i, batch in enumerate(batches, 1):
        filename = f"new_tracks_part_{i}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(batch))

        await client.send_document(
            chat_id=message.chat.id,
            document=filename,
            caption=f"✅ New Tracks Batch {i}/{len(batches)} - {len(batch)} tracks"
        )
        await asyncio.sleep(3)

    await status_msg.edit(
        f"✅ Done!\n"
        f"Total tracks in file: {total_tracks}\n"
        f"Already in DB: {already_in_db}\n"
        f"New tracks files sent: {len(batches)}"
    )


@Client.on_message(filters.command("checkall") & filters.private & filters.reply)
async def check_tracks_in_db(client, message):
    if not message.reply_to_message.document:
        await message.reply("❗ Please reply to a `.txt` file containing track IDs (one per line).")
        return

    status_msg = await message.reply("📥 Downloading file and starting processing...")

    file_path = await message.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    total_tracks = len(lines)
    new_tracks = []
    already_in_db = 0

    for idx, track_id in enumerate(lines, 1):
        try:
            exists = await db.get_dump_file_id(track_id)
            if not exists:
                new_tracks.append(track_id)
            else:
                already_in_db += 1

            if idx % 100 == 0 or idx == total_tracks:
                text = (
                    f"Processing tracks...\n"
                    f"Total tracks: {total_tracks}\n"
                    f"Checked: {idx}\n"
                    f"Already in DB: {already_in_db}\n"
                    f"New tracks to add: {len(new_tracks)}"
                )
                try:
                    await status_msg.edit(text)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                except Exception:
                    pass

        except FloodWait as e:
            await asyncio.sleep(e.x)
            continue
        except Exception as e:
            print(f"Error checking track {track_id}: {e}")
            continue

    batch_size = 20000
    batches = [new_tracks[i:i + batch_size] for i in range(0, len(new_tracks), batch_size)]

    for i, batch in enumerate(batches, 1):
        filename = f"new_tracks_part_{i}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(batch))

        await client.send_document(
            chat_id=message.chat.id,
            document=filename,
            caption=f"✅ New Tracks Batch {i}/{len(batches)} - {len(batch)} tracks"
        )
        await asyncio.sleep(3)

    await status_msg.edit(
        f"✅ Done!\n"
        f"Total tracks in file: {total_tracks}\n"
        f"Already in DB: {already_in_db}\n"
        f"New tracks files sent: {len(batches)}"
    )
    
