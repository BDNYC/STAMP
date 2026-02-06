import requests
from datetime import datetime, timedelta
import os

NASA_API_KEY = os.getenv('NASA_API_KEY', 'DEMO_KEY')  # Free API key
APOD_URL = 'https://api.nasa.gov/planetary/apod'


def get_apod():
    """Fetch Astronomy Picture of the Day"""
    try:
        response = requests.get(APOD_URL, params={'api_key': NASA_API_KEY})
        data = response.json()

        # Only return if it's an image (not a video)
        if data.get('media_type') == 'image':
            return {
                'url': data.get('url'),
                'hdurl': data.get('hdurl'),
                'title': data.get('title'),
                'explanation': data.get('explanation'),
                'date': data.get('date')
            }
        else:
            # Fallback to previous day if today is a video
            return get_apod_fallback()
    except:
        return get_default_space_image()


def get_default_space_image():
    """Fallback image if API fails"""
    return {
        'url': '/static/images/default_space.jpg',
        'title': 'Deep Space',
        'explanation': 'A beautiful view of the cosmos'
    }
