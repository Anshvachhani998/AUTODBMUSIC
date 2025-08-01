from pyrogram import Client, filters
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import logging
import asyncio
from spotipy.exceptions import SpotifyException
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio
from database.db import db 
import os


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

client_id = "920fb2b81c68488188a871f871439951"
client_secret = "5437a98145fa4ceea2f0e53978debf90"
auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=30)

app = Client

def extract_artist_id(url):
    match = re.search(r"artist/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)
    return None

import asyncio
import logging
from spotipy.exceptions import SpotifyException

async def safe_spotify_call_with_rate_limit(func, *args, **kwargs):
    """
    Safely call a Spotify API function (async) with automatic handling of rate limits.
    Retries after waiting if HTTP 429 (rate limit) is encountered.

    Args:
        func: async Spotify API method to call
        *args, **kwargs: parameters for the Spotify API call

    Returns:
        Result of the Spotify API call.
    """
    while True:
        try:
            result = await func(*args, **kwargs)
            return result
        except SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 5))
                logging.warning(f"Rate limited by Spotify, retrying after {retry_after} seconds...")
                await asyncio.sleep(retry_after)
            else:
                logging.error(f"Spotify API error: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error calling Spotify API: {e}")
            raise



@app.on_message(filters.command("artist") & filters.private)
async def artist_songs(client, message):
    if len(message.command) < 2:
        await message.reply("Please send artist Spotify link.\nUsage: /ar <artist_spotify_link>")
        return

    artist_url = message.command[1]
    artist_id = extract_artist_id(artist_url)

    if not artist_id:
        await message.reply("Invalid Spotify artist link. Please send a correct link.")
        return

    status_msg = await message.reply("⏳ Fetching artist tracks, please wait...")

    try:
        # Albums
        albums = []
        results_albums = sp.artist_albums(artist_id, album_type='album', limit=50)
        albums.extend(results_albums['items'])
        while results_albums['next']:
            results_albums = sp.next(results_albums)
            albums.extend(results_albums['items'])

        # Singles
        singles = []
        results_singles = sp.artist_albums(artist_id, album_type='single', limit=50)
        singles.extend(results_singles['items'])
        while results_singles['next']:
            results_singles = sp.next(results_singles)
            singles.extend(results_singles['items'])

        album_ids = set(album['id'] for album in albums)
        single_ids = set(single['id'] for single in singles)

        all_album_ids = list(album_ids.union(single_ids))
        logger.info(f"Total releases: {len(all_album_ids)}")

        all_tracks = []

        # Collect all tracks IDs and names with Spotify safe delay
        for idx, release_id in enumerate(all_album_ids, start=1):
            try:
                tracks = sp.album_tracks(release_id)
                for track in tracks['items']:
                    all_tracks.append((track['id'], track['name']))

                # Spotify rate limit safe: small pause every request
                await asyncio.sleep(0.2)  # 200ms pause

                # Extra pause after every 50 albums
                if idx % 50 == 0:
                    logger.info(f"Processed {idx} releases, taking longer pause to avoid 429...")
                    await asyncio.sleep(3)

            except SpotifyException as e:
                if e.http_status == 429:
                    retry_after = int(e.headers.get("Retry-After", 5))
                    logger.warning(f"Rate limit hit! Waiting for {retry_after} sec...")
                    await asyncio.sleep(retry_after)
                    continue
                else:
                    raise

        total_tracks = len(all_tracks)
        logger.info(f"Total unique tracks: {total_tracks}")

        # Write and send in 10,000 track batches
        max_lines_per_file = 10_000
        batches = [all_tracks[i:i + max_lines_per_file] for i in range(0, total_tracks, max_lines_per_file)]

        artist_name = sp.artist(artist_id)['name'].replace(" ", "_")
        file_prefix = f"{artist_name}_tracks"

        for index, batch in enumerate(batches, start=1):
            file_name = f"{file_prefix}_part_{index}.txt"

            with open(file_name, "w", encoding="utf-8") as f:
                for track_id, track_name in batch:
                    f.write(f"{track_id}\n")

            await client.send_document(
                chat_id=message.chat.id,
                document=file_name,
                caption=f"✅ Part {index} ({len(batch)} tracks)"
            )

            logger.info(f"Sent part {index}")
            await asyncio.sleep(3)  # Telegram safe pause

        await status_msg.edit(f"✅ Done! Total tracks: {total_tracks}")

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit(f"❌ Error: `{e}`")




user_batch = {}


@Client.on_message(filters.command("bulk") & filters.private & filters.reply)
async def artist_bulk_tracks(client, message):
    if not message.reply_to_message.document:
        await message.reply("❗ Please reply to a `.txt` file containing artist links.")
        return

    status_msg = await message.reply("📥 Downloading file...")

    file_path = await message.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    all_tracks = []

    for line in lines:
        match = re.search(r"spotify\.com/artist/([a-zA-Z0-9]+)", line)
        if not match:
            continue

        artist_id = match.group(1)

        try:
            # Albums
            album_ids = set()
            results_albums = sp.artist_albums(artist_id, album_type='album', limit=50)
            album_ids.update([album['id'] for album in results_albums['items']])
            while results_albums['next']:
                results_albums = sp.next(results_albums)
                album_ids.update([album['id'] for album in results_albums['items']])

            # Singles
            results_singles = sp.artist_albums(artist_id, album_type='single', limit=50)
            album_ids.update([single['id'] for single in results_singles['items']])
            while results_singles['next']:
                results_singles = sp.next(results_singles)
                album_ids.update([single['id'] for single in results_singles['items']])

            # Collect tracks
            for idx, release_id in enumerate(album_ids, 1):
                try:
                    tracks = sp.album_tracks(release_id)
                    all_tracks.extend([track['id'] for track in tracks['items']])
                    await asyncio.sleep(0.2)

                    if idx % 50 == 0:
                        await asyncio.sleep(3)

                except SpotifyException as e:
                    if e.http_status == 429:
                        retry_after = int(e.headers.get("Retry-After", 5))
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        raise

        except Exception as e:
            await client.send_message(message.chat.id, f"⚠️ Error fetching artist {artist_id}: {e}")
            continue

    # After processing all artists, send ONE big file
    part_file = f"all_artists_tracks.txt"
    with open(part_file, "w", encoding="utf-8") as f:
        f.write("\n".join(all_tracks))

    await client.send_document(
        chat_id=message.chat.id,
        document=part_file,
        caption=f"✅ All tracks collected. Total tracks: {len(all_tracks)}"
    )

    await status_msg.edit("✅ Done! All artist track IDs fetched.")


@app.on_message(filters.command("extract"))
async def start_batch(client, message):
    user_id = message.from_user.id
    user_batch[user_id] = []
    await message.reply("📥 Please send your first Spotify Playlist or Album link.")

@app.on_message(filters.text & filters.private)
async def handle_links(client, message):
    user_id = message.from_user.id

    if user_id not in user_batch:
        await message.reply("⚠️ Please start with `/extract` first.")
        return

    link = message.text.strip()
    status_msg = await message.reply("⏳ Processing your link, please wait...")
    fetched_ids = []
    total_tracks_count = 0

    try:
        if "playlist" in link:
            playlist_id = link.split("playlist/")[1].split("?")[0]
            playlist = sp.playlist(playlist_id)
            total_tracks_count = playlist['tracks']['total']

            results = sp.playlist_tracks(playlist_id)
            while results:
                for item in results['items']:
                    track = item['track']
                    if track and track['id']:
                        fetched_ids.append(track['id'])
                if results['next']:
                    results = sp.next(results)
                else:
                    results = None

        elif "album" in link:
            album_id = link.split("album/")[1].split("?")[0]
            album = sp.album(album_id)
            total_tracks_count = album['total_tracks']

            results = sp.album_tracks(album_id)
            while results:
                for item in results['items']:
                    if item and item['id']:
                        fetched_ids.append(item['id'])
                if results['next']:
                    results = sp.next(results)
                else:
                    results = None

        else:
            await message.reply("❌ Invalid link. Send a valid Spotify playlist or album link.")
            return

    except Exception as e:
        await message.reply(f"⚠️ Error: `{e}`")
        return

    already_in_db = 0
    new_ids = []

    for tid in fetched_ids:
        dump_file_id = await db.get_dump_file_id(tid)
        if dump_file_id:
            already_in_db += 1
        else:
            if tid not in user_batch[user_id]:
                new_ids.append(tid)

    user_batch[user_id].extend(new_ids)
    await status_msg.delete()

    await message.reply(
        f"✅ Total fetched: {total_tracks_count}\n"
        f"⏭️ Already in DB: {already_in_db}\n"
        f"🆕 Added new: {len(new_ids)}\n"
        f"👉 Current combined: {len(user_batch[user_id])}\n\n"
        f"Add more?",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ Add More", callback_data=f"addmore_{user_id}")],
                [InlineKeyboardButton("✅ Done", callback_data=f"done_{user_id}")]
            ]
        )
    )

@app.on_callback_query(filters.regex(r"addmore_(\d+)"))
async def add_more(client, callback_query):
    await callback_query.answer()
    await callback_query.message.reply("📥 Please send the next playlist/album link.")

@app.on_callback_query(filters.regex(r"done_(\d+)"))
async def done_batch(client, callback_query):
    user_id = int(callback_query.data.split("_")[1])
    tracks = user_batch.get(user_id, [])

    if not tracks:
        await callback_query.answer("⚠️ No tracks found!", show_alert=True)
        return

    file_name = f"user_{user_id}_tracks.txt"
    with open(file_name, "w") as f:
        for tid in tracks:
            f.write(tid + "\n")

    await callback_query.message.reply_document(
        file_name,
        caption=f"✅ Total Combined Tracks: {len(tracks)}"
    )

    os.remove(file_name)
    user_batch.pop(user_id, None)
    await callback_query.answer("✅ Done!", show_alert=True)



import os
import re
import time
import json
import asyncio
import logging
from datetime import datetime
from pyrogram import Client, filters

# Constants - apne hisaab se change kar sakte ho
PROGRESS_FILE = "artist_progress.json"
MAX_REQUESTS_PER_MIN = 55          # Spotify API safe limit approx
MIN_DELAY_BETWEEN_CALLS = 0.8      # 0.8 seconds gap between calls (about 1.25 req/sec)

logger = logging.getLogger("plugins.extract")
logging.basicConfig(level=logging.INFO)

@Client.on_message(filters.command("sa") & filters.private & filters.reply)
async def artist_bulk_tracks(client, message):
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("❗ Please reply to a `.txt` file containing artist links.")
        return

    args = message.text.strip().split()
    manual_skip = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    status_msg = await message.reply("📥 Downloading file...")

    file_path = await message.reply_to_message.download()
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    all_tracks = []
    request_counter = 0
    start_index = 0
    last_reset = time.time()
    last_call_time = 0  # For delay control

    # Progress loading
    if manual_skip is not None:
        start_index = manual_skip
        artist_counter = start_index
        await message.reply(f"⏩ Starting from artist #{start_index+1} (manual skip).")
    elif os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as pf:
                content = pf.read().strip()
                if not content:
                    raise ValueError("Progress file is empty.")
                progress = json.loads(content)
                start_index = progress.get("artist_index", 0)
                request_counter = progress.get("request_counter", 0)
                all_tracks = progress.get("all_tracks", [])
            artist_counter = start_index
            await message.reply(f"🔄 Resuming from artist #{start_index+1} with {request_counter} requests used.")
        except Exception as e:
            await message.reply(f"⚠️ Progress file corrupted or empty. Starting fresh.\n\nError: {e}")
            start_index = 0
            request_counter = 0
            all_tracks = []
            artist_counter = 0
    else:
        await message.reply("🚀 Starting fresh...")
        artist_counter = 0

    async def safe_spotify_call_with_rate_limit(func, *args, **kwargs):
        nonlocal request_counter, last_reset, last_call_time

        # Check per-minute limit
        if request_counter >= MAX_REQUESTS_PER_MIN:
            elapsed = time.time() - last_reset
            if elapsed < 60:
                wait_time = 60 - elapsed
                logger.info(f"⏳ Rate limit reached: waiting {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time)
            request_counter = 0
            last_reset = time.time()

        # Ensure min delay between calls
        now = time.time()
        time_since_last_call = now - last_call_time
        if time_since_last_call < MIN_DELAY_BETWEEN_CALLS:
            await asyncio.sleep(MIN_DELAY_BETWEEN_CALLS - time_since_last_call)

        try:
            # Wrap sync Spotify calls to async if needed
            result = await asyncio.to_thread(func, *args, **kwargs)
            request_counter += 1
            last_call_time = time.time()
            return result
        except Exception as e:
            if hasattr(e, 'http_status') and e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 5))
                logger.warning(f"⛔ Spotify API Rate limit hit, retry after {retry_after}s.")
                await asyncio.sleep(retry_after + 1)
                return await safe_spotify_call_with_rate_limit(func, *args, **kwargs)
            else:
                raise

    for idx in range(start_index, len(lines)):
        line = lines[idx].strip()
        match = re.search(r"spotify\.com/artist/([a-zA-Z0-9]+)", line)
        if not match:
            continue

        artist_id = match.group(1)
        artist_counter += 1

        try:
            logger.info(f"🎤 Fetching albums for Artist {artist_counter}: {artist_id}")
            album_ids = set()

            results = await safe_spotify_call_with_rate_limit(
                sp.artist_albums,
                artist_id,
                album_type='album,single,appears_on,compilation',
                limit=50
            )
            album_ids.update([album['id'] for album in results['items']])

            while results['next']:
                results = await safe_spotify_call_with_rate_limit(sp.next, results)
                album_ids.update([album['id'] for album in results['items']])

            logger.info(f"📀 Total releases for artist {artist_id}: {len(album_ids)}")

            for release_id in album_ids:
                tracks = await safe_spotify_call_with_rate_limit(sp.album_tracks, release_id)

                for track in tracks['items']:
                    track_id = track['id']
                    exists = await db.get_dump_file_id(track_id)
                    if exists:
                        continue
                    all_tracks.append(track_id)

            # Small delay between artists
            await asyncio.sleep(2)

        except Exception as e:
            logger.warning(f"⚠️ Error with artist {artist_id}: {e}")
            await client.send_message(message.chat.id, f"⚠️ Error fetching `{artist_id}`: {e}")
            continue

        # Save/send batches
        if len(all_tracks) >= 5000:
            batch = all_tracks[:5000]
            all_tracks = all_tracks[5000:]
            part_file = f"tracks_part_{artist_counter}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(part_file, "w", encoding="utf-8") as f:
                f.write("\n".join(batch))

            await client.send_document(
                chat_id=message.chat.id,
                document=part_file,
                caption=f"✅ Part from Artist #{artist_counter} (5000 tracks)"
            )
            await asyncio.sleep(3)

        # Save progress json
        with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
            json.dump({
                "artist_index": idx + 1,
                "request_counter": request_counter,
                "all_tracks": all_tracks
            }, pf)

    # Send final batch if left
    if all_tracks:
        part_file = f"tracks_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(part_file, "w", encoding="utf-8") as f:
            f.write("\n".join(all_tracks))

        await client.send_document(
            chat_id=message.chat.id,
            document=part_file,
            caption=f"✅ Final batch — Total tracks: {len(all_tracks)}"
        )

    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    await status_msg.edit("✅ Done! All artist track IDs fetched.")
    os.remove(file_path)

