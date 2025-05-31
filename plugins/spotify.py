from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from spotipy.oauth2 import SpotifyClientCredentials
import spotipy
import re
import requests
import math
from urllib.parse import urlparse
from info import USERBOT_CHAT_ID
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)


client_id = "feef7905dd374fd58ba72e08c0d77e70"
client_secret = "60b4007a8b184727829670e2e0f911ca"
auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager)

song_cache = {}  # {message_id: {"songs": [...], "track_ids": [...]}}
selected_requests = {}  # {userbot_msg_id: {"user_id": ..., "reply_to": ...}}

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

# --- Generate Pagination Buttons ---
def generate_keyboard(song_list, track_ids, page=0, per_page=8):
    start = page * per_page
    end = start + per_page
    buttons = []

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

    return InlineKeyboardMarkup(buttons)

# --- Message Handler ---
@Client.on_message(filters.private & filters.text)
async def handle_spotify_playlist(client, message):
    text = message.text.strip()
    spotify_pattern = r"https?://open\.spotify\.com/playlist/[a-zA-Z0-9]+"

    if re.search(spotify_pattern, text):
        await message.reply("⏳ Fetching Spotify playlist info...")

        try:
            image_url, name, songs, track_ids = get_playlist_info(text)

            # Download thumbnail
            image_data = requests.get(image_url).content
            with open("thumb.jpg", "wb") as f:
                f.write(image_data)

            keyboard = generate_keyboard(songs, track_ids, page=0)

            reply = await message.reply_photo(
                photo="thumb.jpg",
                caption=f"🎧 **Playlist**: {name}\n📀 Total Songs: {len(songs)}\n\n🎵 Select a song below:",
                reply_markup=keyboard
            )

            song_cache[reply.id] = {"songs": songs, "track_ids": track_ids}

        except Exception as e:
            await message.reply(f"⚠️ Error: {e}")

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
    keyboard = generate_keyboard(songs, track_ids, page=page)
    await callback_query.edit_message_reply_markup(reply_markup=keyboard)

# --- Dummy Button Handler ---
@Client.on_callback_query(filters.regex("noop"))
async def handle_noop(client, callback_query):
    await callback_query.answer("🎵 Downloading soon...", show_alert=False)

# --- Track Selection Callback Handler ---
@Client.on_callback_query(filters.regex("trackid:"))
async def handle_trackid_click(client, callback_query):
    track_id = callback_query.data.split(":")[1]
    user_id = callback_query.from_user.id
    msg_id = callback_query.message.id

    data = song_cache.get(msg_id, {})
    songs = data.get("songs", [])
    track_ids = data.get("track_ids", [])

    try:
        index = track_ids.index(track_id)
        song_name = songs[index]
    except:
        song_name = "Selected Song"

    await callback_query.answer(f"🎵 Sending {song_name}")

    spotify_url = f"https://open.spotify.com/track/{track_id}"
    sent = await client.send_message(USERBOT_CHAT_ID, spotify_url)

    # Save track request data
    selected_requests[sent.id] = {
        "user_id": user_id,
        "reply_to": msg_id,
        "status": "waiting"
    }

@Client.on_message(filters.chat(USERBOT_CHAT_ID) & filters.reply)
async def userbot_reply_handler(client, message):
    # Userbot ka reply message
    
    # Reply jis message pe kiya gaya
    replied_msg = message.reply_to_message
    if not replied_msg:
        return

    # Check if original userbot message id hai selected_requests mein
    req = selected_requests.get(replied_msg.id)
    if not req:
        return
    
    original_user_id = req["user_id"]
    
    # Ab userbot ka reply message original user ko bhejo
    await client.send_message(original_user_id, message.text)
    
    # Status update kar lo
    selected_requests[replied_msg.id]["status"] = "replied"



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
    
    return title.lower(), artist.lower()
