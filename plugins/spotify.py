from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from spotipy.oauth2 import SpotifyClientCredentials
import spotipy
import re
import requests
import math
from urllib.parse import urlparse
import logging
import os
from utils import safe_filename, download_with_aria2c, get_song_download_url_by_spotify_url, download_thumbnail
import random
import asyncio
from info import DUMP_CHANNEL_ID
  
logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

logger = logging

client_id = "feef7905dd374fd58ba72e08c0d77e70"
client_secret = "60b4007a8b184727829670e2e0f911ca"
auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager)

song_cache = {}

output_dir = os.path.join(os.getcwd(), "downloads")
os.makedirs(output_dir, exist_ok=True)

# --- Concurrency control: one request at a time per user ---

user_locks = {}


dump_channel_cache = {}  # track_id => dump msg id


async def get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

# --- Spotify info extraction functions ---

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


def get_playlist_info(playlist_url):
    playlist_id = playlist_url.split("/")[-1].split("?")[0]
    playlist = sp.playlist(playlist_id)

    image_url = playlist['images'][0]['url']
    playlist_name = playlist['name']

    song_list = []
    track_ids = []

    for item in playlist['tracks']['items']:
        track = item['track']
        name = track['name']
        artist = track['artists'][0]['name']
        track_id = track['id']
        song_list.append(f"{name} - {artist}")
        track_ids.append(track_id)

    return image_url, playlist_name, song_list, track_ids


import asyncio


download_all_tasks = {}
download_all_cancel_flags = {}

def generate_keyboard(song_list, track_ids, page=0, per_page=8, playlist_message_id=None):
    start = page * per_page
    end = start + per_page
    buttons = []

    # Song buttons
    for i in range(start, min(end, len(song_list))):
        buttons.append([
            InlineKeyboardButton(
                text=f"{i+1}. {song_list[i]}",
                callback_data=f"trackid:{track_ids[i]}"
            )
        ])

    total_pages = math.ceil(len(song_list) / per_page)
    nav_buttons = []

    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"page:{page - 1}"))

    nav_buttons.append(InlineKeyboardButton(f"📄 Page {page + 1}/{total_pages}", callback_data="noop"))

    if end < len(song_list):
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"page:{page + 1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    if playlist_message_id is not None:
        buttons.append([
            InlineKeyboardButton("⬇️ Download All", callback_data=f"downloadall:{playlist_message_id}")
        ])

    return InlineKeyboardMarkup(buttons)


# --- Pagination Callback Handler ---

@Client.on_callback_query(filters.regex("page:"))
async def paginate_callback(client, callback_query):
    page = int(callback_query.data.split(":")[1])
    message_id = callback_query.message.id

    data = song_cache.get(message_id)
    if not data:
        await callback_query.answer("❌ Song list expired.", show_alert=True)
        return

    songs = data["songs"]
    track_ids = data["track_ids"]
    

    keyboard = generate_keyboard(
        songs,
        track_ids,
        page=page,
        per_page=8,
        playlist_message_id=message_id
    )

    await callback_query.edit_message_reply_markup(reply_markup=keyboard)

import asyncio

@Client.on_callback_query(filters.regex(r"downloadall:(\d+)"))
async def handle_download_all(client, callback_query):
    message_id = int(callback_query.data.split(":")[1])
    user_id = callback_query.from_user.id
    playlist_message_id = callback_query.from_user.id

    data = song_cache.get(message_id)
    if not data:
        logging.info(f"data {song_cache} ")
        logging.info(f"take it data {data} //  {user_id} /// {message_id} ")
        await callback_query.answer("❌ Playlist data expired.", show_alert=True)
        return

    songs = data["songs"]
    track_ids = data["track_ids"]
    playlist_message_id = data["playlist_message_id"]

    key = (user_id, message_id)
    if key in download_all_tasks:
        await callback_query.answer("⚠️ Download all already in progress.", show_alert=True)
        return

    download_all_cancel_flags[key] = False

    async def download_all_songs():
        sent_count = 0
        total = len(track_ids)
        status_msg = await client.send_message(user_id, f"⬇️ Starting download of {total} songs...")

        for i, track_id in enumerate(track_ids, start=1):
            if download_all_cancel_flags.get(key):
                await status_msg.edit(f"❌ Download cancelled by user after sending {sent_count} songs.")
                break

            # Step 1: Check dump DB cache for existing file_id
            dump_file_id = await db.get_dump_file_id(track_id)
            if dump_file_id:
                try:
                    await client.send_audio(
                        user_id,
                        dump_file_id,
                        caption=f"🎵 (From Cache) Song {i} of {total}"
                    )
                    sent_count += 1
                    await status_msg.edit(f"⬇️ Sending cached song {i} of {total}\n"
                                          f"✅ Sent: {sent_count}\n"
                                          f"⏳ Remaining: {total - sent_count}")
                    continue
                except Exception as e:
                    logging.info(f"Failed to send cached song {track_id}: {e}")
                    await db.col.delete_one({"track_id": track_id})  # remove broken cache

            spotify_url = f"https://open.spotify.com/track/{track_id}"
            track_info = extract_track_info(spotify_url)
            if not track_info:
                await client.send_message(user_id, f"⚠️ Failed to fetch info for song {i}. Skipping...")
                continue

            title, artist, thumb_url = track_info
            cancel_keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Cancel Download", callback_data=f"cancel_download:{message_id}")]]
            )

            await status_msg.edit(f"⬇️ Downloading song {i} of {total}: **{title}**\n"
                                  f"✅ Sent: {sent_count}\n"
                                  f"⏳ Remaining: {total - sent_count}", reply_markup=cancel_keyboard)

            try:
                song_title, song_url = await get_song_download_url_by_spotify_url(spotify_url)
            except Exception:
                await client.send_message(user_id, f"⚠️ Error fetching song {i}. Skipping...")
                continue

            if not song_url:
                await client.send_message(user_id, f"❌ Song not found: {title}. Skipping...")
                continue

            base_name = safe_filename(song_title)
            safe_name = f"{base_name}_{random.randint(100, 999)}.mp3"
            download_path = os.path.join(output_dir, safe_name)

            success = await download_with_aria2c(song_url, output_dir, safe_name)
            if not success or not os.path.exists(download_path):
                await client.send_message(user_id, f"❌ Failed to download: {song_title}. Skipping...")
                continue

            thumb_path = os.path.join(output_dir, safe_filename(song_title) + ".jpg")
            thumb_success = await download_thumbnail(thumb_url, thumb_path)

            try:
                if thumb_success and os.path.exists(thumb_path):
                    sent_msg = await client.send_audio(
                        user_id,
                        download_path,
                        caption=f"🎵 **{song_title}**\n👤 {artist}",
                        thumb=thumb_path,
                        title=song_title,
                        performer=artist
                    )
                else:
                    sent_msg = await client.send_audio(
                        user_id,
                        download_path,
                        caption=f"🎵 **{song_title}**\n👤 {artist}",
                        title=song_title,
                        performer=artist
                    )

                # Upload to dump channel fresh with track_id in caption
                dump_caption = f"🎵 **{song_title}**\n👤 {artist}\n🆔 {track_id}"
                dump_msg = await client.send_audio(
                    DUMP_CHANNEL_ID,
                    audio=sent_msg.audio.file_id,
                    caption=dump_caption,
                    thumb=thumb_path if thumb_success and os.path.exists(thumb_path) else None,
                    title=song_title,
                    performer=artist
                )

                # Save dump file_id in DB
                await db.save_dump_file_id(track_id, dump_msg.audio.file_id)

                sent_count += 1
                await status_msg.edit(f"⬇️ Downloading song {i} of {total}: **{song_title}**\n"
                                      f"✅ Sent: {sent_count}\n"
                                      f"⏳ Remaining: {total - sent_count}")

            except Exception as e:
                logging.error(f"Error sending song {song_title}: {e}")
                await client.send_message(user_id, f"⚠️ Failed to send: {song_title}. Skipping...")

            finally:
                if os.path.exists(download_path):
                    os.remove(download_path)
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)

        else:
            if not download_all_cancel_flags.get(key):
                await status_msg.edit(f"✅ All songs sent successfully! Total: {sent_count}")

        # Cleanup
        download_all_tasks.pop(key, None)
        download_all_cancel_flags.pop(key, None)

    task = asyncio.create_task(download_all_songs())
    download_all_tasks[key] = task

    await callback_query.answer("⬇️ Started downloading all songs. Check your PM.")


@Client.on_callback_query(filters.regex(r"cancel_download:(\d+)"))
async def handle_cancel_download(client, callback_query):
    message_id = int(callback_query.data.split(":")[1])
    user_id = callback_query.from_user.id

    key = (user_id, message_id)
    if key not in download_all_tasks:
        await callback_query.answer("❌ No active download to cancel.", show_alert=True)
        return

    # Set cancel flag to True
    download_all_cancel_flags[key] = True

    await callback_query.answer("❌ Cancelling download...", show_alert=True)


# --- Main Message Handler with concurrency lock ---

@Client.on_message(filters.private & filters.text)
async def handle_spotify_link(client, message):
    user_id = message.from_user.id
    text = message.text.strip()

    playlist_pattern = r"https?://open\.spotify\.com/playlist/[a-zA-Z0-9]+"
    track_pattern = r"https?://open\.spotify\.com/track/[a-zA-Z0-9]+"

    # Locking omitted for brevity — add your lock system here if needed

    if re.search(playlist_pattern, text):
        # Handle playlist
        await message.reply("⏳ Fetching Spotify playlist info...")
        try:
            image_url, name, songs, track_ids = get_playlist_info(text)
            image_data = requests.get(image_url).content
            with open("thumb.jpg", "wb") as f:
                f.write(image_data)

            reply = await message.reply_photo(
                photo="thumb.jpg",
                caption=f"🎧 **Playlist**: {name}\n📀 Total Songs: {len(songs)}\n\n🎵 Select a song below:"
            )
            keyboard = generate_keyboard(songs, track_ids, page=0, playlist_message_id=reply.id)
            await reply.edit_reply_markup(reply_markup=keyboard)

            song_cache[reply.id] = {"songs": songs, "track_ids": track_ids, "playlist_message_id": reply.id}
        except Exception as e:
            await message.reply(f"⚠️ Error: {e}")

        return

    elif re.search(track_pattern, text):
        # Handle single track directly
        ansh = await message.reply("⏳ Fetching Spotify track info...")

        # Extract track_id from URL
        track_id = re.search(r"track/([a-zA-Z0-9]+)", text).group(1)
        spotify_url = f"https://open.spotify.com/track/{track_id}"

        # Step 1: Check DB cache for dump file_id
        dump_file_id = await db.get_dump_file_id(track_id)
        if dump_file_id:
            try:
                await client.send_audio(
                    user_id,
                    dump_file_id,
                    caption=f"🎵 **(From Cache)**"
                )
                await ansh.delete()
                return
            except Exception as e:
                logging.info(f"Cache send failed: {e}")
                # Remove from DB if file is missing
                await db.col.delete_one({"track_id": track_id})

        # Step 2: Fetch track info and download
        track_info = extract_track_info(spotify_url)
        if not track_info:
            await message.reply("⚠️ Could not fetch track info. Please check the link.")
            await ansh.delete()
            return

        title, artist, thumb_url = track_info

        wait_msg = await message.reply(f"🔄 Please wait... fetching your song: **{title}**")
        await ansh.delete()

        try:
            song_title, song_url = await get_song_download_url_by_spotify_url(spotify_url)
        except Exception as e:
            await wait_msg.edit("⚠️ An error occurred while fetching the song.")
            return

        if not song_url:
            await wait_msg.edit("❌ Song not found via API.")
            return

        base_name = safe_filename(song_title)
        unique_number = random.randint(100, 999)
        safe_name = f"{base_name}_{unique_number}.mp3"
        download_path = os.path.join(output_dir, safe_name)

        await wait_msg.edit(f"⬇️ Downloading **{song_title}**...")

        success = await download_with_aria2c(song_url, output_dir, safe_name)
        if not success or not os.path.exists(download_path):
            await wait_msg.edit("❌ Failed to download the song.")
            return

        thumb_path = os.path.join(output_dir, safe_filename(song_title) + ".jpg")
        thumb_success = await download_thumbnail(thumb_url, thumb_path)

        try:
            await wait_msg.edit(f"📤 Uploading **{song_title}**...")

            if thumb_success and os.path.exists(thumb_path):
                sent_msg = await client.send_audio(
                    user_id,
                    download_path,
                    caption=f"🎵 **{song_title}**\n👤 {artist}",
                    thumb=thumb_path,
                    title=song_title,
                    performer=artist
                )
            else:
                sent_msg = await client.send_audio(
                    user_id,
                    download_path,
                    caption=f"🎵 **{song_title}**\n👤 {artist}",
                    title=song_title,
                    performer=artist
                )

            # Step 3: Upload fresh to dump channel with track_id in caption
            dump_caption = f"🎵 **{song_title}**\n👤 {artist}\n🆔 {track_id}"
            dump_msg = await client.send_audio(
                DUMP_CHANNEL_ID,
                audio=sent_msg.audio.file_id,
                caption=dump_caption,
                thumb=thumb_path if thumb_success and os.path.exists(thumb_path) else None,
                title=song_title,
                performer=artist
            )

            # Step 4: Save dump file_id in DB for future
            await db.save_dump_file_id(track_id, dump_msg.audio.file_id)

            await wait_msg.delete()

        except Exception as e:
            logging.error(f"Error sending audio: {e}")
            await wait_msg.edit("⚠️ Failed to send the song file.")

        finally:
            if os.path.exists(download_path):
                os.remove(download_path)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

        return

    else:
        await message.reply("⚠️ Please send a valid Spotify track or playlist link.")








from database.db import db  # tera mongo class instance

@Client.on_callback_query(filters.regex("trackid:"))
async def handle_trackid_click(client, callback_query):
    user_id = callback_query.from_user.id

    lock = await get_user_lock(user_id)
    if lock.locked():
        await callback_query.answer("⚠️ You already have a request running. Please wait.", show_alert=True)
        return

    async with lock:
        track_id = callback_query.data.split(":")[1]
        spotify_url = f"https://open.spotify.com/track/{track_id}"
        track_info = extract_track_info(spotify_url)
        if not track_info:
            await client.send_message(user_id, "⚠️ Failed to fetch track info.")
            return

        title, artist, thumb_url = track_info

        await callback_query.answer("🎵 Fetching your song...")

        # --- Step 1: Check DB cache for dump_msg_id ---
        dump_file_id = await db.get_dump_file_id(track_id)
        if dump_file_id:
            try:
                await client.send_audio(
                    user_id,
                    dump_file_id,
                    caption=f"🎵 **{title}**\n👤 {artist}")
                return
            except Exception as e:
                # Forward failed (message deleted?), remove cache and continue
                logging.info(f"Forward failed: {e}")
                # Optionally remove from DB:
                await db.col.delete_one({"track_id": track_id})

        # --- Step 2: Download flow ---

        # Extract track info
        track_info = extract_track_info(spotify_url)
        if not track_info:
            await client.send_message(user_id, "⚠️ Failed to fetch track info.")
            return

        title, artist, thumb_url = track_info

        wait_msg = await client.send_message(user_id, "🔄 Please wait... fetching your song.")

        try:
            song_title, song_url = await get_song_download_url_by_spotify_url(spotify_url)
        except Exception:
            await wait_msg.edit("⚠️ Error fetching the song.")
            return

        if not song_url:
            await wait_msg.edit("❌ Song not found.")
            return

        base_name = safe_filename(song_title)
        safe_name = f"{base_name}_{random.randint(100, 999)}.mp3"
        download_path = os.path.join(output_dir, safe_name)

        await wait_msg.edit(f"⬇️ Downloading **{song_title}**...")

        success = await download_with_aria2c(song_url, output_dir, safe_name)
        if not success or not os.path.exists(download_path):
            await wait_msg.edit("❌ Download failed.")
            return

        thumb_path = os.path.join(output_dir, safe_filename(song_title) + ".jpg")
        thumb_success = await download_thumbnail(thumb_url, thumb_path)

        try:
            await wait_msg.edit(f"📤 Uploading **{song_title}**...")

            if thumb_success and os.path.exists(thumb_path):
                sent_msg = await client.send_audio(
                    user_id,
                    download_path,
                    caption=f"🎵 **{song_title}**\n👤 {artist}",
                    thumb=thumb_path,
                    title=song_title,
                    performer=artist
                )
            else:
                sent_msg = await client.send_audio(
                    user_id,
                    download_path,
                    caption=f"🎵 **{song_title}**\n👤 {artist}",
                    title=song_title,
                    performer=artist
                )

            # --- Send to dump channel (fresh upload) ---
            dump_caption = f"🎵 **{song_title}**\n👤 {artist}\n🆔 {track_id}"

            dump_msg = await client.send_audio(
                DUMP_CHANNEL_ID,
                audio=sent_msg.audio.file_id,
                caption=dump_caption,
                thumb=thumb_path if thumb_success and os.path.exists(thumb_path) else None,
                title=song_title,
                performer=artist
            )

            # --- Save to DB ---
            await db.save_dump_file_id(track_id, dump_msg.audio.file_id)

            await wait_msg.delete()

        except Exception as e:
            logging.error(f"Error sending audio: {e}")
            await wait_msg.edit("⚠️ Failed to send audio.")

        finally:
            if os.path.exists(download_path):
                os.remove(download_path)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)




# ✅ Batch RUN CMD: File se IDs read karke one-by-one call with CANCEL
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Dictionary to track cancellation flags per user
run_cancel_flags = {}

@Client.on_message(filters.command("run") & filters.reply)
async def run_tracks(client, message):
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

    # Unique key for this user to track cancel
    key = f"run_{user_id}"
    run_cancel_flags[key] = False

    cancel_keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel Batch", callback_data=f"cancel_run:{user_id}")]]
    )

    status_msg = await message.reply(
        f"📂 **Batch Download Started!**\n"
        f"🎵 Total: **{total}**\n"
        f"✅ Sent: **0**\n"
        f"⏳ Remaining: **{total}**",
        reply_markup=cancel_keyboard
    )

    for idx, track_id in enumerate(track_ids, 1):
        # Check if cancel was pressed
        if run_cancel_flags.get(key):
            await status_msg.edit(
                f"❌ Batch cancelled by user.\n"
                f"🎵 Total: **{total}**\n"
                f"✅ Sent: **{sent_count}**\n"
                f"❌ Failed: **{len(failed_tracks)}**",
                reply_markup=None
            )
            break

        try:
            spotify_url = f"https://open.spotify.com/track/{track_id}"
            track_info = extract_track_info(spotify_url)
            if not track_info:
                await client.send_message(user_id, f"⚠️ Failed to fetch info for `{track_id}`. Skipping...")
                failed_tracks.append(track_id)
                continue

            title, artist, thumb_url = track_info

            await status_msg.edit(
                f"⬇️ Downloading {idx} of {total}: **{title}**\n"
                f"✅ Sent: {sent_count}\n"
                f"⏳ Remaining: {total - sent_count}",
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
                sent_msg = await client.send_audio(
                    user_id,
                    download_path,
                    caption=f"🎵 **{song_title}**\n👤 {artist}",
                    thumb=thumb_path if thumb_success and os.path.exists(thumb_path) else None,
                    title=song_title,
                    performer=artist
                )

                dump_caption = f"🎵 **{song_title}**\n👤 {artist}\n🆔 {track_id}"
                dump_msg = await client.send_audio(
                    DUMP_CHANNEL_ID,
                    audio=sent_msg.audio.file_id,
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
                    f"⏳ Remaining: {total - sent_count}",
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
        await status_msg.edit(
            f"✅ **Batch Done!**\n"
            f"🎵 Total: **{total}**\n"
            f"✅ Sent: **{sent_count}**\n"
            f"❌ Failed: **{len(failed_tracks)}**",
            reply_markup=None
        )

    if failed_tracks:
        await client.send_message(
            user_id,
            "⚠️ Some tracks failed:\n" + "\n".join(failed_tracks)
        )

    run_cancel_flags.pop(key, None)
    os.remove(file)

# ✅ CANCEL Button handler
@Client.on_callback_query(filters.regex(r"cancel_run:(\d+)"))
async def cancel_run_batch(client, callback_query):
    user_id = int(callback_query.data.split(":")[1])
    key = f"run_{user_id}"
    run_cancel_flags[key] = True
    await callback_query.answer("✅ Batch cancelled!", show_alert=True)

