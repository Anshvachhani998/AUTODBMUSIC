# utils.py

import aiohttp
import asyncio
import logging
import os
import re
import urllib.parse
import random
from urllib.parse import quote
import requests
from plugins.api import SpotMate
import random




logger = logging.getLogger(__name__)

def safe_filename(name: str) -> str:
    """Remove unsafe filesystem characters from a filename."""
    return re.sub(r'[\\/*?:"<>|]', '_', name)

import asyncio

aria2c_semaphore = asyncio.Semaphore(1)  # max 1 parallel

async def download_with_aria2c(url, output_dir, filename):
    async with aria2c_semaphore:
        # optional small delay before starting
        await asyncio.sleep(2)

        cmd = [
            "aria2c",
            "-x", "2",
            "-s", "2",
            "-k", "1M",
            "--max-tries=5",
            "--retry-wait=5",
            "--timeout=60",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "-d", output_dir,
            "-o", filename,
            url
        ]
       
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

   
        if process.returncode == 0:
         
            return True
        else:
            logger.error(f"aria2c failed with exit code {process.returncode}")
            # optionally implement exponential backoff retry here
            return False



def ms_to_minutes(ms):
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{str(seconds).zfill(2)}"

def spotify_download_primary(url):
    if not url:
        raise ValueError("❌ Error: URL is missing!")

    headers = {
        'Content-Type': 'application/json',
        'Origin': 'https://spotiydownloader.com',
        'Referer': 'https://spotiydownloader.com/id',
        'User-Agent': 'Mozilla/5.0'
    }

    try:
        meta_response = requests.post(
            'https://spotiydownloader.com/api/metainfo',
            json={'url': url},
            headers=headers,
            timeout=15
        )
        meta_response.raise_for_status()
    except requests.RequestException as e:
        raise ConnectionError(f"❌ Error fetching meta info: {e}")

    meta = meta_response.json()
    if not meta.get('success') or not meta.get('id'):
        raise ValueError("❌ Failed to get song info. Maybe wrong URL?")

    try:
        dl_response = requests.post(
            'https://spotiydownloader.com/api/download',
            json={'id': meta['id']},
            headers=headers,
            timeout=15
        )
        dl_response.raise_for_status()
    except requests.RequestException as e:
        raise ConnectionError(f"❌ Error fetching download link: {e}")

    result = dl_response.json()
    if not result.get('success') or not result.get('link'):
        raise ValueError("❌ Failed to get download link.")

    return {
        'artist': meta.get('artists') or meta.get('artist') or 'Unknown',
        'title': meta.get('title') or 'Unknown',
        'duration': ms_to_minutes(meta['duration_ms']) if meta.get('duration_ms') else 'Unknown',
        'image': meta.get('cover'),
        'download': quote(result['link'], safe=':/?&=')
    }



async def get_song_download_url_by_spotify_url(url, max_retries=3, retry_delay=3):
    loop = asyncio.get_event_loop()

    for attempt in range(1, max_retries + 1):
        methods = ['primary', 'secondary']
        random.shuffle(methods)

        first = methods[0]
        second = methods[1]

        try:
            if first == 'primary':
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, spotify_download_primary, url),
                    timeout=10
                )
                if result and result.get('download'):
                    song_title = f"{result['artist']} - {result['title']}"
                    return song_title, result['download']
            else:
                song_title, song_url = await asyncio.wait_for(
                    spotify_download_secondary(url),
                    timeout=20
                )
                if song_url:
                    return song_title, song_url

        except Exception as e:
            logger.info(f"Attempt {attempt}: {first} method failed with error: {e}")

        try:
            if second == 'primary':
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, spotify_download_primary, url),
                    timeout=10
                )
                if result and result.get('download'):
                    song_title = f"{result['title']}"
                    return song_title, result['download']
            else:
                song_title, song_url = await asyncio.wait_for(
                    spotify_download_secondary(url),
                    timeout=20
                )
                if song_url:
                    return song_title, song_url

        except Exception as e:
            logger.info(f"Attempt {attempt}: {second} method failed with error: {e}")

        logger.info(f"Attempt {attempt} failed, retrying after {retry_delay} seconds...")
        await asyncio.sleep(retry_delay)

    # 3 attempts ke baad bhi nahi mila toh None return karo
    return None, None



async def spotify_download_secondary(url: str):
    loop = asyncio.get_event_loop()

    def spotmate_flow():
        sm = SpotMate()
        info = sm.info(url)

        artists = []
        if info.get('artists'):
            for a in info['artists']:
                artists.append(a.get('name'))
        artist_name = ", ".join(artists) if artists else "Unknown"

        title = info.get('name') or info.get('title') or "Unknown"
        
        result = sm.convert(url)
        if not result or 'url' not in result or not result['url']:
            raise Exception("SpotMate convert failed: No URL found.")

        download_url = result['url']
        sm.clear()

        return title, download_url

    return await loop.run_in_executor(None, spotmate_flow)





async def download_thumbnail(thumb_url: str, output_path: str) -> bool:
    if not thumb_url:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(thumb_url) as resp:
                if resp.status == 200:
                    with open(output_path, "wb") as f:
                        f.write(await resp.read())
                    logging.info(f"Thumbnail downloaded to {output_path}")
                    return True
    except Exception as e:
        logging.error(f"Thumbnail download failed: {e}")

    return False
