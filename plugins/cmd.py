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

