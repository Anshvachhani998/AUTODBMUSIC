import requests
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class SpotMate:
    def __init__(self):
        self.session = requests.Session()
        self._token = None


    def _visit(self):
        headers = {
            'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36',
        }

        response = self.session.get('https://spotmate.online/en', headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        token = soup.find('meta', {'name': 'csrf-token'})

        if not token:
            logger.error("❌ CSRF token not found!")
            raise Exception('CSRF token not found.')

        self._token = token['content']
     
    def _get_headers(self):
        headers = {
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://spotmate.online',
            'referer': 'https://spotmate.online/en',
            'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36',
            'x-csrf-token': self._token,
        }
        return headers

    def info(self, spotify_url):
        if not self._token:
            self._visit()

        logger.info(f"📥 Fetching info for: {spotify_url}")
        payload = {'spotify_url': spotify_url}

        response = self.session.post(
            'https://spotmate.online/getTrackData',
            json=payload,
            headers=self._get_headers()
        )
        response.raise_for_status()
        return response.json()

    def convert(self, spotify_url):
        if not self._token:
            self._visit()

        payload = {'urls': spotify_url}

        response = self.session.post(
            'https://spotmate.online/convert',
            json=payload,
            headers=self._get_headers()
        )
        response.raise_for_status()
        return response.json()

    def clear(self):
        self.session.close()
        self._token = None
