#!/usr/bin/env python
# @Name: util.py
# @Project: DSUAuthBot/
# @Author: Gaelin Shupe
# @Created: 9/19/23


import asyncio
import dataclasses
import json
import logging
from random import choice as rand_choice
from string import ascii_letters, digits
from typing import Callable, Coroutine

import discord
import pymysql
import requests

logger = logging.getLogger()


class UrlButton(discord.ui.View):
    def __init__(self, url: str, label: str, emoji: discord.Emoji = None):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                url=url,
            )
        )


class BasicTextInput(discord.ui.Modal):
    def __init__(
        self,
        title: str,
        prompt: str,
        *,
        validator: Callable[[str], Coroutine[None, None, bool]],
        callback: Callable[[discord.Interaction, str], Coroutine[None, None, None]],
        error_message: str = "Invalid input!",
        placeholder: str = None,
        default: str = None,
        min_length: int = 1,
        max_length: int = 100,
    ):
        super().__init__(title=title)
        self.callback = callback
        self.validator = validator
        self.error_message = error_message
        self.input = discord.ui.TextInput(
            label=prompt,
            style=discord.TextStyle.paragraph if max_length is None or max_length > 100 else discord.TextStyle.short,
            placeholder=placeholder,
            default=default,
            min_length=min_length,
            max_length=max_length,
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.command_failed:
            return
        try:
            if await self.validator(self.input.value):
                await self.callback(interaction, self.input.value)
            else:
                await interaction.response.send_message(
                    embed=discord.Embed(colour=discord.Colour.red(), title=self.error_message.format(self.input.value)),
                    ephemeral=True,
                )
        except:
            await interaction.response.send_message(
                content="There was an unknown error processing your requesst!", ephemeral=True
            )


def get_position(email: str) -> str:
    """Guess user's position with the university based on email address"""
    if "@trojans.dsu.edu" in email.lower() or "@pluto.dsu.edu" in email.lower():
        return "student"
    if "@dsu.edu" in email:
        return "professor"
    return "non-dsu"


def value_or_none(value: str) -> str | None:
    if value is not None:
        if value != "":
            return value
    return None


class Config:
    """Configuration manager"""

    def __init__(self, config_path: str):
        self.config_path: str = config_path
        self._data: dict = {}
        self.auth_channels: list[int] = []
        self.reload_config()

    def reload_config(self):
        """Reload the config file from disk"""
        with open(self.config_path) as f:
            self._data = json.load(f)
        self.auth_channels = [int(server.get("verify_channel", "0")) for server in self.servers.values()]
        logger.info("Loaded server config")

    def instructor_role(self, guild_id: int | str) -> int:
        """Get the instructor role id for a server"""
        return int(self.servers.get(str(guild_id), {}).get("instructor_role", 0))

    def student_role(self, guild_id: int | str) -> int:
        """Get the student role id for a server"""
        return int(self.servers.get(str(guild_id), {}).get("student_role", 0))

    def instructor_role_remove(self, guild_id: int | str) -> int:
        """Get the instructor role id for a server"""
        return int(self.servers.get(str(guild_id), {}).get("instructor_role_remove", 0))

    def student_role_remove(self, guild_id: int | str) -> int:
        """Get the student role id for a server"""
        return int(self.servers.get(str(guild_id), {}).get("student_role_remove", 0))

    @property
    def servers(self) -> dict:
        """Get all configured servers"""
        return self._data["servers"]


class DBC:
    """Database connection manager"""

    TABLES = [
        """CREATE TABLE IF NOT EXISTS users (
id            BIGINT(20)                                                            NOT NULL PRIMARY KEY,
discord_tag   VARCHAR(40)                                                           NOT NULL,
email         VARCHAR(64)                                                           NULL,
name          VARCHAR(64)                                                           NULL,
position      ENUM ('non-dsu', 'student', 'professor', 'unknown') DEFAULT 'unknown' NOT NULL,
ialab_user    VARCHAR(64)                                                           NULL,
first_seen    TIMESTAMP                                                             NULL,
verify_date   TIMESTAMP                                                             NULL
       );""",
        """CREATE TABLE IF NOT EXISTS oauth (
state              CHAR(16)                              NOT NULL,
user_id            BIGINT(20)                            NOT NULL,
authorization_code VARCHAR(2048)                         NULL,
access_token       VARCHAR(8192)                         NULL,
time               TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL ON UPDATE CURRENT_TIMESTAMP(),
CONSTRAINT user_id FOREIGN KEY (user_id) REFERENCES users (id) ON UPDATE CASCADE ON DELETE CASCADE
);""",
    ]

    @dataclasses.dataclass
    class User:
        """Represents a verified user"""

        email: str
        name: str
        position: str
        ialab_username: str

    def __init__(self, *, host: str, user: str, password: str, db: str):
        self.db = pymysql.connect(
            host=host,
            user=user,
            password=password,
            db=db,
            autocommit=True,
        )
        self._cursor = self.db.cursor()
        for table in self.TABLES:
            self._cursor.execute(table)
        self.lock = asyncio.Lock()

    async def _execute(self, query: str, args: tuple, response: bool = False) -> tuple | None:
        async with self.lock:
            self.db.ping()  # reconnect=True
            self._cursor.execute(query, args)
            self.db.commit()
            if response:
                return self._cursor.fetchone()

    async def init_oauth_session(self, user_id: str | int) -> str:
        """
        Create a new oauth session in the DB
        :param user_id: Discord user ID
        :return: Session state ID
        """
        state = "".join(rand_choice(ascii_letters + digits) for _ in range(16))
        await self._execute("INSERT INTO oauth (state, user_id) VALUE (%s,%s)", (state, user_id))
        return state

    async def add_user(self, user: discord.Member | discord.User) -> None:
        """Add a discord user to the database"""
        await self._execute(
            "INSERT INTO users (id, discord_tag, first_seen) VALUES (%s, %s, CURRENT_TIMESTAMP()) ON DUPLICATE KEY UPDATE discord_tag = %s;",
            (user.id, user.name, user.name),
        )

    async def get_user(self, user_id: str | int) -> User | None:
        """
        Get the user object for a verified user
        :param user_id: Discord ID of user
        :return: User object or None if user is invalid
        """
        user_info = await self._execute(
            "SELECT email,name,position,ialab_username FROM users WHERE id = %s", (user_id,), response=True
        )
        if user_info is None:
            return None
        return self.User(email=user_info[0], name=user_info[1], position=user_info[2], ialab_username=user_info[3])

    async def update_user(self, uid: str | int, *, email: str, name: str, position: str, username: str) -> None:
        """Update a user in the DB"""
        # Replacing the id kills the fk to verify thus deleting the pending verifications
        #     "REPLACE INTO discord.users (id, discordTag, email, name, position) VALUES (%s, %s, %s, %s, %s)"
        await self._execute(
            "UPDATE users SET discord_tag = %s, email = %s, name = %s, position = %s, verify_date = CURRENT_TIMESTAMP() where id = %s;",
            (username, email, name, position, uid),
        )

    async def update_ialab_username(self, uid: str | int, ialab_username: str):
        """Set the user's ialab username"""
        await self._execute(
            "UPDATE users SET ialab_username = %s where id = %s;",
            (ialab_username, uid),
        )

    async def update_session(self, state: str, code: str, access_token: str) -> None:
        """Update an oauth session with the code and access token."""
        await self._execute(
            "UPDATE oauth SET access_token = %s, authorization_code = %s WHERE state = %s;", (access_token, code, state)
        )

    async def get_state_user_id(self, state: str) -> str | None:
        """Get the user ID responsible for an oauth state"""
        row = await self._execute("SELECT user_id FROM oauth WHERE state = %s;", (state,), response=True)
        if row is None:
            return None
        return row[0]

    async def get_access_token(self, code: str) -> str | None:
        """Get the access token associated with an authorization code"""
        row = await self._execute(
            "SELECT access_token FROM oauth WHERE authorization_code = %s;", (code,), response=True
        )
        if row is None:
            return None
        return row[0]


class AzureOauth:
    """Simple oauth handler for o365"""

    BASE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/"

    def __init__(self, *, client_id: str, redirect_uri: str, scopes: list, secret: str):
        self.client_id = client_id
        self.scopes = scopes
        self.redirect_uri = redirect_uri
        self.secret = secret

    def request(self, state: str) -> str:
        """Build an oauth request url"""
        return (
            f"{self.BASE_URL}authorize"
            "?response_type=code"
            f"&client_id={self.client_id}"
            f"&scope={' '.join(self.scopes)}"
            f"&redirect_uri={self.redirect_uri}"
            f"&state={state}"
            # f"&prompt=consent"
            # f"&prompt=none"
            f"&auth_params=domain_hint=dsu.edu&domain_hint=dsu.edu"
        )

    async def get_access_token(self, code: str) -> str | None:
        """Use an authorization code to redeem an access token"""
        auth_response = requests.post(
            f"{self.BASE_URL}token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.secret,
            },
        )
        try:
            resp_json = auth_response.json()
        except requests.exceptions.JSONDecodeError:
            logger.warning("Non json auth response")
            logger.warning(auth_response.text)
            return None

        if auth_response.status_code != 200:
            # 54005 = Already redeemed
            if 54005 in resp_json.get("error_codes", []):
                return None
            logger.warning("Could not process oauth")
            try:
                logger.warning(json.dumps(resp_json, indent=2))
            except Exception as e:
                logger.warning(f"Error processing oauth response: {e}")
                logger.warning(auth_response.text)
            return None

        return resp_json["access_token"]


def get_vapp_url_from_id(vapp_id: str) -> str:
    if vapp_id.startswith("vapp-"):
        vapp_id = vapp_id[5:]
    return f"https://vcloud.ialab.dsu.edu/tenant/DefSec/vdcs/15a9a5ed-d859-4039-b1e7-55476cfe58ef/vapp/vapp-{vapp_id}/vcd-vapp-vms"
