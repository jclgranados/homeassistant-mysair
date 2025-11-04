import aiohttp
from .const import API_BASE_URL

class MySairAPI:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.session = aiohttp.ClientSession()
        self.access_token = None
        self.refresh_token = None
        self.aws_data = None

    async def login(self):
        async with self.session.post(f"{API_BASE_URL}user/login",
                                     json={"email": self.email, "password": self.password}) as resp:
            data = await resp.json()
            entity = data["entity"]
            self.access_token = entity["access_token"]
            self.refresh_token = entity["refresh_token"]
            self.aws_data = entity
            return entity

    async def refresh_tokens(self):
        async with self.session.put(f"{API_BASE_URL}user/refreshtokens",
                                    json={"refresh_token": self.refresh_token}) as resp:
            data = await resp.json()
            entity = data["entity"]
            self.access_token = entity["access_token"]
            self.refresh_token = entity["refresh_token"]
            return entity

    async def get_locations(self):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with self.session.get(f"{API_BASE_URL}locations", headers=headers) as resp:
            return await resp.json()

    async def get_installations(self, location_id):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with self.session.get(f"{API_BASE_URL}installations?location_id={location_id}&validated=1", headers=headers) as resp:
            return await resp.json()

    async def get_devices(self, installation_ref):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with self.session.get(f"{API_BASE_URL}devices?installation_ref={installation_ref}", headers=headers) as resp:
            return await resp.json()

    async def send_instruction(self, payload):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with self.session.post(f"{API_BASE_URL}send/instruction", headers=headers, json=payload) as resp:
            return await resp.json()

    async def refresh_aws_credentials(self):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with self.session.put(f"{API_BASE_URL}user/refreshawscredentials", headers=headers) as resp:
            data = await resp.json()
            self.aws_data = data["entity"]
            return self.aws_data

