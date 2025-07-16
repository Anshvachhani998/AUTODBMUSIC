from pyrogram import Client, filters
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import logging
import asyncio
from spotipy.exceptions import SpotifyException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

client_id = "17d04bf5a73040a8926605bfa0daeea3"
client_secret = "7f2af00d12ec4b6ab3dfce13002290d5"
auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager)

app = Client

def extract_artist_id(url):
    match = re.search(r"artist/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)
    return None

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
