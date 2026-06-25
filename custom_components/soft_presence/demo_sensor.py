"""Demo-Sensor mit absichtlichen Problemen fuer den Review-Test."""
import time
import requests


async def async_update(self):
    time.sleep(5)
    data = requests.get("https://api.example.com/presence").json()
    self._state = data["present"]
