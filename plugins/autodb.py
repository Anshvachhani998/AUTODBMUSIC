import os
import time
import random
import logging
import asyncio
from urllib.parse import urlparse
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import tempfile
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
from utils import safe_filename, download_with_aria2c, get_song_download_url_by_spotify_url, download_thumbnail
import random
import asyncio
from info import DUMP_CHANNEL_ID, FAILD_CHAT_ID
from database.db import db


logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

logger = logging

client_id = "5561376fd0234838863a8c3a6cbb0865"
client_secret = "fa12e995f56c48a28e28fb056e041d18"
auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager)

song_cache = {}
run_cancel_flags = {}

output_dir = os.path.join(os.getcwd(), "downloads")
os.makedirs(output_dir, exist_ok=True)


def extract_track_info(spotify_url: str):
    parsed = urlparse(spotify_url)

    if "track" not in parsed.path:
        logging.warning("URL does not contain 'track' in path. Returning None.")
        return None

    track_id = parsed.path.split("/")[-1].split("?")[0]
    try:
        result = sp.track(track_id)
    except Exception as e:
        logging.error(f"Error fetching track info from Spotify API: {e}")
        return None

    title = result['name']
    artist = result['artists'][0]['name']

    album_images = result['album'].get('images', [])
    image_url = album_images[0]['url'] if album_images else None

    return title, artist, image_url
  
def format_seconds(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return ' '.join(parts)

@Client.on_message(filters.command("run") & filters.reply)
async def run_tracksssf(client, message):
    if not message.reply_to_message.document:
        await message.reply("⚠️ Please reply to a `.txt` file containing track IDs.")
        return

    file = await client.download_media(message.reply_to_message.document)
    user_id = message.from_user.id

    with open(file, "r") as f:
        track_ids = [line.strip() for line in f if line.strip()]

    total = len(track_ids)
    sent_count = 0
    failed_tracks = []
    skipped_tracks = []

    key = f"run_{user_id}"
    run_cancel_flags[key] = False

    cancel_keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel Batch", callback_data=f"cancel_run:{user_id}")]]
    )

    # 🕒 Note start time
    start_time = time.time()

    status_msg = await message.reply(
        f"📂 **Batch Download Started!**\n"
        f"🎵 Total: **{total}**\n"
        f"✅ Sent: **0**\n"
        f"⏳ Remaining: **{total}**",
        reply_markup=cancel_keyboard
    )

    for idx, track_id in enumerate(track_ids, 1):
        if run_cancel_flags.get(key):
            end_time = time.time()
            formatted_time = format_seconds(int(end_time - start_time))
            await status_msg.edit(
                f"❌ Batch cancelled by user.\n"
                f"🎵 Total: **{total}**\n"
                f"✅ Sent: **{sent_count}**\n"
                f"⏭️ Skipped: **{len(skipped_tracks)}**\n"
                f"❌ Failed: **{len(failed_tracks)}**\n"
                f"⏳ Time Taken: **{formatted_time}**",
                reply_markup=None
            )
            break

        dump_file_id = await db.get_dump_file_id(track_id)
        if dump_file_id:
            skipped_tracks.append(track_id)
            continue

        try:
            spotify_url = f"https://open.spotify.com/track/{track_id}"
            track_info = extract_track_info(spotify_url)
            if not track_info:
                await client.send_message(user_id, f"⚠️ Failed to fetch info for `{track_id}`. Skipping...")
                failed_tracks.append(track_id)
                await status_msg.edit(
                    f"⚠️ Failed to fetch info for some tracks.\n"
                    f"✅ Sent: {sent_count}\n"
                    f"⏭️ Skipped: {len(skipped_tracks)}\n"
                    f"❌ Failed: {len(failed_tracks)}\n"
                    f"⏳ Remaining: {total - sent_count - len(skipped_tracks) - len(failed_tracks)}",
                    reply_markup=cancel_keyboard
                )
                continue

            title, artist, thumb_url = track_info

            await status_msg.edit(
                f"⬇️ Downloading {idx} of {total}: **{title}**\n"
                f"✅ Sent: {sent_count}\n"
                f"⏭️ Skipped: {len(skipped_tracks)}\n"
                f"❌ Failed: {len(failed_tracks)}\n"
                f"⏳ Remaining: {total - sent_count - len(skipped_tracks) - len(failed_tracks)}",
                reply_markup=cancel_keyboard
            )

            try:
                song_title, song_url = await get_song_download_url_by_spotify_url(spotify_url)
            except Exception:
                await client.send_message(user_id, f"⚠️ Error fetching link for `{title}`. Skipping...")
                failed_tracks.append(track_id)
                continue

            if not song_url:
                await client.send_message(user_id, f"❌ No download link for `{title}`. Skipping...")
                failed_tracks.append(track_id)
                continue

            base_name = safe_filename(song_title)
            safe_name = f"{base_name}_{random.randint(100, 999)}.mp3"
            download_path = os.path.join(output_dir, safe_name)

            success = await download_with_aria2c(song_url, output_dir, safe_name)
            if not success or not os.path.exists(download_path):
                await client.send_message(user_id, f"❌ Failed to download **{song_title}**. Skipping...")
                failed_tracks.append(track_id)
                continue

            thumb_path = os.path.join(output_dir, safe_filename(song_title) + ".jpg")
            thumb_success = await download_thumbnail(thumb_url, thumb_path)

            try:
                dump_caption = f"🎵 **{song_title}**\n👤 {artist}\n🆔 {track_id}"
                dump_msg = await client.send_audio(
                    DUMP_CHANNEL_ID,
                    download_path,
                    caption=dump_caption,
                    thumb=thumb_path if thumb_success and os.path.exists(thumb_path) else None,
                    title=song_title,
                    performer=artist
                )
                await db.save_dump_file_id(track_id, dump_msg.audio.file_id)

                sent_count += 1

                await status_msg.edit(
                    f"⬇️ Downloading {idx} of {total}: **{song_title}**\n"
                    f"✅ Sent: {sent_count}\n"
                    f"⏭️ Skipped: {len(skipped_tracks)}\n"
                    f"❌ Failed: {len(failed_tracks)}\n"
                    f"⏳ Remaining: {total - sent_count - len(skipped_tracks) - len(failed_tracks)}",
                    reply_markup=cancel_keyboard
                )
                await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"Send failed for {song_title}: {e}")
                await client.send_message(user_id, f"⚠️ Failed to send **{song_title}**. Skipping...")
                failed_tracks.append(track_id)

            finally:
                if os.path.exists(download_path):
                    os.remove(download_path)
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)

        except Exception as e:
            logging.error(f"Unhandled error for {track_id}: {e}")
            failed_tracks.append(track_id)

    if not run_cancel_flags.get(key):
        end_time = time.time()
        formatted_time = format_seconds(int(end_time - start_time))
        await status_msg.edit(
            f"✅ **Batch Done!**\n"
            f"🎵 Total: **{total}**\n"
            f"✅ Sent: **{sent_count}**\n"
            f"⏭️ Skipped: **{len(skipped_tracks)}**\n"
            f"❌ Failed: **{len(failed_tracks)}**\n"
            f"⏳ Time Taken: **{formatted_time}**",
            reply_markup=None
        )

    if failed_tracks:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as tmp_file:
            tmp_file.write("\n".join(failed_tracks))
            failed_file_path = tmp_file.name

        await client.send_document(
            user_id,
            failed_file_path,
            caption=f"⚠️ Some tracks failed. Here is the list of {len(failed_tracks)}"
        )
        await client.send_document(
            FAILD_CHAT_ID,
            failed_file_path,
            caption=f"⚠️ Failed {len(failed_tracks)} tracks log for user `{user_id}`."
        )
        os.remove(failed_file_path)

    run_cancel_flags.pop(key, None)
    os.remove(file)


# Cancel Button handler
@Client.on_callback_query(filters.regex(r"cancel_run:(\d+)"))
async def cancel_run_batch(client, callback_query):
    user_id = int(callback_query.data.split(":")[1])
    key = f"run_{user_id}"
    run_cancel_flags[key] = True
    await callback_query.answer("✅ Batch cancelled!", show_alert=True)
