#!/usr/bin/env python
# @Name: defsec_api.py
# @Project: DSUAuthBot/
# @Author: Gaelin Shupe
# @Created: 9/19/23
import asyncio

import requests

from util import get_vapp_url_from_id


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

    async def get_template_id(self, template_name: str, catalog: str = None) -> str | None:
        return (await self.get_templates(template_name, catalog=catalog)).get(template_name, None)

    async def deploy_lesson(self, username: str, template_name: str = "", template_id: str = "") -> str:
        resp = requests.post(
            f"{self.host}/deploy",
            headers=self.headers,
            json={
                "template": template_name,
                "catalog": "",
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
                return get_vapp_url_from_id(vapp_id)

    async def deploy_team(self, team_name: str, users: list[str], template_id: str = "") -> str:
        resp = requests.post(
            f"{self.host}/deploy",
            headers=self.headers,
            json={
                "template": "",
                "catalog": "DefSec_Lessons",
                "template_id": template_id,
                "start": False,
                "snapshot": False,
                "no_cache": False,
                "deploy_lease_seconds": 259200,  # 3 days
                "storage_lease_seconds": 2592000,  # 30 days
                "variants": [team_name],
                "force_synchronous": False,  # no bad :/
                "make_owner": False,
            },
        )
        action_id = list(resp.json()["status"].values())[0]
        for _ in range(200):
            await asyncio.sleep(5)
            if (vapp_id := await self.check_status(action_id)) is not None:
                await self.set_access(vapp_id, owner=None, users=users)
                return f"https://vcloud.ialab.dsu.edu/tenant/DefSec/vdcs/1b507d5f-2faf-4d90-b7c2-27ef48d9ff88/vapp/vapp-{vapp_id}/vcd-vapp-vms"

    async def set_access(self, vapp_id: str, owner: str, users: list[str]) -> bool:
        resp = requests.post(
            f"{self.host}/access/{vapp_id}",
            headers=self.headers,
            data={"owner": owner, "perms": {user: "Read" for user in users}},
        )
        return resp.json()["success"]

    async def check_status(self, action_id: str):
        resp = requests.get(
            f"{self.host}/deploy_action/{action_id}",
            headers=self.headers,
        )
        return resp.json()["id"] if resp.status_code == 200 else None

    async def get_lessons(self, partial: str) -> dict:
        return await self.get_templates(partial, "DefSec_Lessons")

    async def get_templates(self, partial: str, catalog: str = None) -> dict:
        if catalog is not None:
            url = f"{self.host}/catalog/{catalog}/templates/{partial}"
        else:
            url = f"{self.host}/templates/{partial}"
        resp = requests.get(url, headers=self.headers)
        return resp.json()["templates"] if resp.status_code == 200 else {}

    async def get_catalogs(self, catalog: str) -> list[str]:
        resp = requests.get(
            f"{self.host}/catalogs/{catalog}",
            headers=self.headers,
        )
        return resp.json()["catalogs"] if resp.status_code == 200 else []

    async def get_vapps_for_owner(self, vapp_partial: str, owner: str) -> dict[str, str]:
        resp = requests.get(
            f"{self.host}/user/{owner}/vapps/{vapp_partial}",
            headers=self.headers,
        )
        return resp.json() if resp.status_code == 200 else {}

    async def share_vapp(self, vapp_id: str, users: list[str], level="FullControl") -> bool:
        resp = requests.post(
            f"{self.host}/vapp/{vapp_id}/access", headers=self.headers, json={"level": level, "users": users}
        )
        return resp.status_code == 200
