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

client_credentials = [
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

async def check_credentials(session, client_id, client_secret):
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "client_credentials"}

    try:
        async with session.post("https://accounts.spotify.com/api/token", headers=headers, data=data) as resp:
            status = resp.status
            if status == 200:
                return f"✅ `{client_id}` — Working"
            elif status == 429:
                return f"⚠️ `{client_id}` — Rate Limited"
            elif status in [400, 401]:
                return f"❌ `{client_id}` — Invalid"
            else:
                return f"❓ `{client_id}` — Unknown Error ({status})"
    except Exception as e:
        return f"❌ `{client_id}` — Error: {e}"

@Client.on_message(filters.command("test") & filters.private)
async def check_spotify_clients(_, message: Message):
    status_msg = await message.reply("🔍 Checking all Spotify client credentials...")

    async with aiohttp.ClientSession() as session:
        tasks = [
            check_credentials(session, cid, secret)
            for cid, secret in client_credentials
        ]
        results = await asyncio.gather(*tasks)

    result_text = "\n".join(results)

    if len(result_text) > 4096:
        result_text = result_text[:4090] + "\n\n⚠️ Output truncated..."

    await status_msg.edit_text(f"🔎 **Spotify Client Check Result:**\n\n{result_text}")
    
