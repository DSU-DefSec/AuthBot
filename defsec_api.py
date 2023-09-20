#!/usr/bin/env python
# @Name: defsec_api.py
# @Project: DSUAuthBot/
# @Author: Gaelin Shupe
# @Created: 9/19/23
import asyncio

import requests


class DefSecApi:
    def __init__(self, host: str, api_key: str):
        self.api_key = api_key
        self.host = host
        self.headers = {"Content-Type": "application/json", "X-Api-Key": self.api_key}

    async def is_valid_user(self, user: str):
        if user is None:
            return False
        resp = requests.get(
            f"{self.host}/user/{user}",
            headers=self.headers,
        )
        if resp.status_code == 200:
            return resp.json()["valid"]
        return False

    async def get_template_id(self, template_name: str) -> str | None:
        return (await self.get_lessons(template_name)).get(template_name, None)

    async def deploy_lesson(self, username: str, template_name: str = "", template_id: str = "") -> str:
        resp = requests.post(
            f"{self.host}/deploy",
            headers=self.headers,
            json={
                "template": template_name,
                "catalog": "DefSec_Lessons",
                "template_id": template_id,
                "start": False,
                "snapshot": False,
                "no_cache": False,
                "deploy_lease_seconds": 7200,
                "storage_lease_seconds": 432000,
                "variants": [username],
                "force_synchronous": False,  # no bad :/
                "make_owner": True,
            },
        )
        action_id = list(resp.json()["status"].values())[0]
        for _ in range(200):
            await asyncio.sleep(5)
            if (vapp_id := await self.check_status(action_id)) is not None:
                return f"https://vcloud.ialab.dsu.edu/tenant/DefSec/vdcs/1b507d5f-2faf-4d90-b7c2-27ef48d9ff88/vapp/vapp-{vapp_id}/vcd-vapp-vms"

    async def check_status(self, action_id: str):
        resp = requests.get(
            f"{self.host}/deploy_action/{action_id}",
            headers=self.headers,
        )
        return resp.json()["id"] if resp.status_code == 200 else None

    async def get_lessons(self, partial: str) -> dict:
        return await self.get_templates("DefSec_Lessons", partial)

    async def get_templates(self, catalog: str, partial: str) -> dict:
        resp = requests.get(
            f"{self.host}/catalog/{catalog}/templates/{partial}",
            headers=self.headers,
        )
        return resp.json()["templates"] if resp.status_code == 200 else {}

    async def get_catalogs(self, catalog: str) -> list[str]:
        resp = requests.get(
            f"{self.host}/catalogs/{catalog}",
            headers=self.headers,
        )
        return resp.json()["catalogs"] if resp.status_code == 200 else []
