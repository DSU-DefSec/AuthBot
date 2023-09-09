#!/usr/bin/python
import asyncio
import base64
import dataclasses
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from json import load
from random import choice as rand_choice
from string import ascii_letters, digits

import discord
import pymysql
import requests
from discord.ext import commands

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

logging.basicConfig()
logger = logging.getLogger("authbot")
logger.setLevel(logging.INFO)


class DBC:
    TABLES = [
        """CREATE TABLE IF NOT EXISTS users (
id            BIGINT(20)                                                            NOT NULL PRIMARY KEY,
discord_tag   VARCHAR(40)                                                           NOT NULL,
email         VARCHAR(64)                                                           NULL,
name          VARCHAR(64)                                                           NULL,
position      ENUM ('non-dsu', 'student', 'professor', 'unknown') DEFAULT 'unknown' NOT NULL,
first_seen    TIMESTAMP                                                             NULL,
verify_date   TIMESTAMP                                                             NULL,
verify_server BIGINT(20)                                                            NULL
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
        email: str
        name: str
        position: str

    def __init__(self, *, host: str, user: str, password: str, db: str):
        self.db = pymysql.connect(
            host=host,
            user=user,
            password=password,
            db=db,
            autocommit=True,
        )
        self.cursor = self.db.cursor()
        for table in self.TABLES:
            self.cursor.execute(table)

    def _execute(self, query: str, args: tuple) -> None:
        self.db.ping(reconnect=True)
        self.cursor.execute(query, args)
        self.db.commit()

    def init_oauth_session(self, user_id: str | int) -> str:
        state = "".join(rand_choice(ascii_letters + digits) for _ in range(16))
        self._execute("INSERT INTO oauth (state, user_id) VALUE (%s,%s)", (state, user_id))
        return state

    def add_user(self, user_id: str | int, user_name: str) -> None:
        self._execute(
            "INSERT INTO users (id, discord_tag, first_seen) VALUES (%s, %s, CURRENT_TIMESTAMP()) ON DUPLICATE KEY UPDATE discord_tag = %s;",
            (user_id, user_name, user_name),
        )

    def get_user(self, user_id: str | int) -> User:
        self._execute("SELECT email,name,position FROM users WHERE id = %s", user_id)
        user_info = self.cursor.fetchone()
        if user_info is None:
            return None
        return self.User(email=user_info[0], name=user_info[1], position=user_info[2])

    def get_authorization_code(self, session: str) -> (int, str):
        self._execute("SELECT user_id, authorization_code FROM oauth WHERE state = %s;", session)
        row = self.cursor.fetchone()
        if row is None:
            return None, None
        return int(row[0]), row[1]

    def update_user(self, uid: str | int, *, email: str, name: str, position: str, username: str) -> None:
        # Replacing the id kills the fk to verify thus deleting the pending verifications
        #     "REPLACE INTO discord.users (id, discordTag, email, name, position) VALUES (%s, %s, %s, %s, %s)"
        self._execute(
            "UPDATE users set discord_tag = %s, email = %s, name = %s, position = %s where id = %s;",
            (username, email, name, position, uid),
        )

    def update_session(self, code: str, access_token: str) -> None:
        self._execute("UPDATE oauth SET access_token = %s WHERE authorization_code = %s;", (access_token, code))

    def get_access_token(self, code: str) -> str:
        self._execute("SELECT access_token FROM oauth WHERE authorization_code = %s;", code)
        row = self.cursor.fetchone()
        if row is None:
            return None
        return row[0]


class AzureOauth:
    BASE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/"

    def __init__(self, *, client_id: str, redirect_uri: str, scopes: list, secret: str):
        self.client_id = client_id
        self.scopes = scopes
        self.redirect_uri = redirect_uri
        self.secret = secret

    def request(self, state: str):
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

    def get_access_token(self, code: str):
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
        except:
            logger.warning("Non json auth response")
            logger.warning(auth_response.text)
            return None

        if auth_response.status_code != 200:
            # 54005 = Already redeemed
            if 54005 in resp_json.get("error_codes", []):
                return dbc.get_access_token(code)
            logger.warning("Could not process oauth")
            try:
                logger.warning(json.dumps(resp_json, indent=2))
            except:
                logger.warning(auth_response.text)
            return None

            # raise Exception("Could not process oauth")

        return resp_json["access_token"]


class Config:
    def __init__(self, config_path: str):
        self.config_path: str = config_path
        self._data: dict = {}
        self.auth_channels: list[int] = []
        self.reload_config()

    def reload_config(self):
        self._data = json.load(open(self.config_path))
        self.auth_channels = [int(server.get("verify_channel", "0")) for server in self.servers.values()]
        logger.info("Loaded server config")

    def instructor_role(self, guild_id: int | str) -> int:
        return int(self.servers.get(str(guild_id), {}).get("instructor_role", None))

    def student_role(self, guild_id: int | str) -> int:
        return int(self.servers.get(str(guild_id), {}).get("student_role", None))

    @property
    def servers(self) -> dict:
        return self._data["servers"]


config = Config("config.json")


def get_position(email: str) -> str:
    if "@trojans.dsu.edu" in email.lower() or "@pluto.dsu.edu" in email.lower():
        return "student"
    if "@dsu.edu" in email:
        return "professor"
    return "non-dsu"


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    await bot.tree.sync()
    bot.loop.create_task(start_websocket())
    known_users = []

    for guild in bot.guilds:
        logger.info(f"Initializing members in {guild}")
        members: AsyncIterator = guild.fetch_members(limit=None)
        try:
            while True:
                member = await anext(members)
                if member.id not in known_users:
                    known_users.append(member.id)
                    add_user_to_db(member)
        except StopAsyncIteration:
            pass
    logger.info(f"Total users: {len(known_users)}")


def add_user_to_db(user: discord.Member | discord.User):
    dbc.add_user(user.id, user.name)


async def confirm_roles(member: discord.Member):
    user = dbc.get_user(member.id)
    if not user:
        logger.critical(f"Tried to verify null user {member} ({member.id})")
        return
    verify_reason = f"Verified to {user.name} ({user.email})"
    if user.name:
        try:
            await member.edit(nick=user.name, reason=verify_reason)
        except discord.errors.Forbidden:
            logger.warning(f"Could not set nick for {member} on {member.guild}")
    try:
        if user.position == "professor":
            await member.add_roles(member.guild.get_role(config.instructor_role(member.guild.id)), reason=verify_reason)
            await member.add_roles(member.guild.get_role(config.student_role(member.guild.id)), reason=verify_reason)
        if user.position == "student":
            await member.add_roles(member.guild.get_role(config.student_role(member.guild.id)), reason=verify_reason)

    except discord.errors.Forbidden:
        logger.warning(f"Could not set roles for {member} on {member.guild}")


@bot.event
async def on_member_join(member: discord.Member):
    logger.info(f"+{member} in {member.guild}")
    add_user_to_db(member)
    await confirm_roles(member)


async def start_websocket():
    server = await asyncio.start_server(handle_socket_connection, "127.0.0.1", 8888)
    logger.info(f"Listening on {server.sockets[0].getsockname()}")
    async with server:
        await server.serve_forever()


async def handle_socket_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    # logger.debug(f"Got connection on {addr}")
    data = await reader.read(100)
    session = data.decode().strip()
    logger.info(f"Received {session=!r} from {addr}")
    user_id, code = dbc.get_authorization_code(session)
    if code is None:
        try:
            writer.write(b"x")
        except Exception as e:
            logger.warning(e)
    else:
        writer.write(b"good" if (await verify_member(user_id, code)) else b"x")
    writer.close()


async def verify_member(uid: int, code: str) -> bool:
    access_token = oauth.get_access_token(code)
    if access_token is None:
        return False
    # Not enough padding = :( Extra padding = :)
    user_info = json.loads(base64.b64decode(access_token.split(".")[1] + "===").decode())
    email = user_info["unique_name"]
    last_name, first_name = user_info["family_name"], user_info["given_name"]
    position = get_position(email)
    name = f"{first_name} {last_name}"
    username = bot.get_user(uid).name

    dbc.update_session(code, access_token=access_token)
    dbc.update_user(uid, email=email, name=name, position=position, username=username)

    with open("verify.log", "a") as log:
        log.write(f"{datetime.now()} {username} ({uid}) => {email}\n")
    logger.info(f"Verified {username} ({uid}) to {email}")
    for server_id, server in config.servers.items():
        try:
            member = bot.get_guild(int(server_id)).get_member(uid)
        except (ValueError, AttributeError):
            # User not in server
            continue
        await confirm_roles(member)
        try:
            if "verify_log" in server:
                await bot.get_channel(int(server["verify_log"])).send(
                    f"{position.capitalize()} {name} ({email}) linked {member.mention}"
                )
        except (ValueError, AttributeError):
            logger.warning(f"Could not write to verify log channel {server.get('verify_log','')} in {server_id}")
    return True


@bot.tree.command(name="verify", description="Verify to a DSU account")
async def verify(interaction: discord.Interaction) -> None:
    """/verify"""
    user = interaction.user
    add_user_to_db(user)
    session = dbc.init_oauth_session(user.id)
    await interaction.response.send_message(
        embed=discord.Embed(title="Click here to verify DSU status", url=oauth.request(session)),
        ephemeral=True,
    )


@bot.command(name="config")
@commands.has_permissions(administrator=True)
async def config_command(ctx):
    if str(ctx.guild.id) not in config.servers:
        await ctx.send("Not configured for this server")
    else:
        await ctx.send(
            embed=discord.Embed(
                title="Config for this server",
                description=f"""
Verify channel: <#{config.servers[str(ctx.guild.id)]["verify_channel"]}>
Verify log: <#{config.servers[str(ctx.guild.id)]["verify_log"]}>
Student Role: <@&{config.servers[str(ctx.guild.id)]["student_role"]}>
Professor Role: <@&{config.servers[str(ctx.guild.id)]["instructor_role"]}>
""",
            )
        )


@bot.command(name="reloadconfig")
@commands.has_permissions(administrator=True)
async def reload(ctx):
    await ctx.message.delete(delay=2)
    config.reload_config()


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)
    # if message.channel.id in config.auth_channels:
    #     async with message.channel.typing():
    # await send_oauth_to_user(message.author)
    # await message.add_reaction("✅")
    # await message.delete(delay=25)


with open("creds.json", "r") as c:
    creds = load(c)
oauth = AzureOauth(
    client_id=creds["oauth"]["client_id"],
    secret=creds["oauth"]["client_secret"],
    scopes=["openid+User.Read"],
    redirect_uri="https://auth.defsec.club/azure/auth",
)

dbc = DBC(host=creds["db"]["host"], user=creds["db"]["user"], password=creds["db"]["password"], db=creds["db"]["db"])
bot.run(creds["token"])
