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
from re import compile as re_compile
from string import ascii_letters, digits

import discord
import pymysql
import requests

logging.basicConfig(filename="run.log")
logger = logging.getLogger("authbot")
logger.setLevel(logging.INFO)


class AuthBot(discord.Client):
    def __init__(self, *, intents: discord.Intents, web_port: int = 8080):
        super().__init__(intents=intents)
        self.web_port = web_port
        self.tree = discord.app_commands.CommandTree(self)
        # noinspection PyTypeChecker
        self.tree.command(name="verify", description="Verify to a DSU account")(self.command_verify)

    async def on_ready(self):
        """
        Fired when the bot had fully loaded.
        Start webserver thread and get all users
        """
        logger.info(f"Logged in as {self.user}")

        server = await self.loop.create_server(lambda: RedirectReceiver(), "127.0.0.1", self.web_port)
        logger.info(f"Webserver listening on 127.0.0.1:{self.web_port}")
        self.loop.create_task(start_webserver(server))

        await self.tree.sync()

        known_users = []
        for guild in self.guilds:
            logger.info(f"Initializing members in {guild}")
            members: AsyncIterator = guild.fetch_members(limit=None)
            try:
                while True:
                    member = await anext(members)
                    if member.id not in known_users:
                        known_users.append(member.id)
                        await dbc.add_user(member)
            except StopAsyncIteration:
                pass
        logger.info(f"Total users: {len(known_users)}")

    # noinspection PyMethodMayBeStatic
    async def on_member_join(self, member: discord.Member) -> None:
        """
        Fired when a member joins a server
        """
        logger.info(f"+{member} in {member.guild}")
        await dbc.add_user(member)
        await confirm_roles(member)

    # noinspection PyMethodMayBeStatic
    async def command_verify(self, interaction: discord.Interaction) -> None:
        """/verify"""
        user = interaction.user
        await dbc.add_user(user)
        session = await dbc.init_oauth_session(user.id)
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(
            embed=discord.Embed(title="Click here to verify DSU status", url=oauth.request(session)),
            ephemeral=True,
        )

        # @self.command(name="config")
        # @commands.has_permissions(administrator=True)
        # async def config_command(ctx):
        #     if str(ctx.guild.id) not in config.servers:
        #         await ctx.send("Not configured for this server")
        #     else:
        #         await ctx.send(
        #             embed=discord.Embed(
        #                 title="Config for this server",
        #                 description=f"""
        # Verify channel: <#{config.servers[str(ctx.guild.id)]["verify_channel"]}>
        # Verify log: <#{config.servers[str(ctx.guild.id)]["verify_log"]}>
        # Student Role: <@&{config.servers[str(ctx.guild.id)]["student_role"]}>
        # Professor Role: <@&{config.servers[str(ctx.guild.id)]["instructor_role"]}>
        # """,
        #             )
        #         )
        #
        #
        # @self.command(name="reloadconfig")
        # @commands.has_permissions(administrator=True)
        # async def reload(ctx):
        #     await ctx.message.delete(delay=2)
        #     config.reload_config()
        # @bot.event
        # async def on_message(message: discord.Message):
        #     if message.author == bot.user:
        #         return
        #     await bot.process_commands(message)
        #     # if message.channel.id in config.auth_channels:
        #     #     async with message.channel.typing():
        #     # await send_oauth_to_user(message.author)
        #     # await message.add_reaction("✅")
        #     # await message.delete(delay=25)


bot = AuthBot(intents=discord.Intents.all(), web_port=1157)


class DBC:
    """Database connection manager"""

    TABLES = [
        """CREATE TABLE IF NOT EXISTS users (
id            BIGINT(20)                                                            NOT NULL PRIMARY KEY,
discord_tag   VARCHAR(40)                                                           NOT NULL,
email         VARCHAR(64)                                                           NULL,
name          VARCHAR(64)                                                           NULL,
position      ENUM ('non-dsu', 'student', 'professor', 'unknown') DEFAULT 'unknown' NOT NULL,
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
        :return: User object
        """
        user_info = await self._execute(
            "SELECT email,name,position FROM users WHERE id = %s", (user_id,), response=True
        )
        if user_info is None:
            return None
        return self.User(email=user_info[0], name=user_info[1], position=user_info[2])

    async def update_user(self, uid: str | int, *, email: str, name: str, position: str, username: str) -> None:
        """Update a user in the DB"""
        # Replacing the id kills the fk to verify thus deleting the pending verifications
        #     "REPLACE INTO discord.users (id, discordTag, email, name, position) VALUES (%s, %s, %s, %s, %s)"
        await self._execute(
            "UPDATE users set discord_tag = %s, email = %s, name = %s, position = %s, verify_date = CURRENT_TIMESTAMP() where id = %s;",
            (username, email, name, position, uid),
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

    async def get_access_token(self, code: str):
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
                return await dbc.get_access_token(code)
            logger.warning("Could not process oauth")
            try:
                logger.warning(json.dumps(resp_json, indent=2))
            except Exception as e:
                logger.warning(f"Error processing oauth response: {e}")
                logger.warning(auth_response.text)
            return None

        return resp_json["access_token"]


class Config:
    """Configuration manager"""

    def __init__(self, config_path: str):
        self.config_path: str = config_path
        self._data: dict = {}
        self.auth_channels: list[int] = []
        self.reload_config()

    def reload_config(self):
        """Reload the config file from disk"""
        self._data = json.load(open(self.config_path))
        self.auth_channels = [int(server.get("verify_channel", "0")) for server in self.servers.values()]
        logger.info("Loaded server config")

    def instructor_role(self, guild_id: int | str) -> int:
        """Get the instructor role id for a server"""
        return int(self.servers.get(str(guild_id), {}).get("instructor_role", None))

    def student_role(self, guild_id: int | str) -> int:
        """Get the student role id for a server"""
        return int(self.servers.get(str(guild_id), {}).get("student_role", None))

    @property
    def servers(self) -> dict:
        """Get all configured servers"""
        return self._data["servers"]


config = Config("config.json")


def get_position(email: str) -> str:
    """Guess user's position with the university based on email address"""
    if "@trojans.dsu.edu" in email.lower() or "@pluto.dsu.edu" in email.lower():
        return "student"
    if "@dsu.edu" in email:
        return "professor"
    return "non-dsu"


async def confirm_roles(member: discord.Member) -> None:
    """
    Check the user's nick and roles and confirm that they are correct.
    ** Roles are only added
    """
    user = await dbc.get_user(member.id)
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


async def verify_member(state: str, code: str) -> str:
    """
    Verify an oauth response
    :param state: oauth state code
    :param code: oauth authorization code
    :return: Status message for user
    """
    user_id = await dbc.get_state_user_id(state)
    if user_id is None:
        return "Invalid or expired code 🙁"
    access_token = await oauth.get_access_token(code)
    if access_token is None:
        return "Invalid or expired code 🙁"
    # Not enough padding = :( Extra padding = :)
    user_info = json.loads(base64.b64decode(access_token.split(".")[1] + "===").decode())
    email = user_info["unique_name"]
    last_name, first_name = user_info["family_name"], user_info["given_name"]
    position = get_position(email)
    name = f"{first_name} {last_name}"
    username = bot.get_user(int(user_id)).name

    await dbc.update_session(state, code=code, access_token=access_token)
    await dbc.update_user(user_id, email=email, name=name, position=position, username=username)

    with open("verify.log", "a") as log:
        log.write(f"{datetime.now()} {username} ({user_id}) => {email}\n")

    logger.info(f"Verified {username} ({user_id}) to {email}")
    for server_id, server in config.servers.items():
        try:
            member = bot.get_guild(int(server_id)).get_member(int(user_id))
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
    return "Verified 👍"


async def start_webserver(server) -> None:
    """Start serving the webserver. Infinitely blocking"""
    async with server:
        await server.serve_forever()


class RedirectReceiver(asyncio.Protocol):
    """Very simple webserver to receive oauth"""

    # noinspection RegExpAnonymousGroup
    REQUEST_LINE_RE = re_compile(r"^GET /.*\?code=([a-zA-Z0-9._-]+)&state=([a-zA-Z0-9]{16}).+ HTTP/\d.\d$")

    # noinspection PyMissingOrEmptyDocstring,PyAttributeOutsideInit
    def connection_made(self, transport) -> None:
        self.transport = transport

    def data_received(self, data) -> None:
        """Data received on the socket"""
        asyncio.create_task(self.async_data_received(data))

    async def async_data_received(self, data) -> None:
        """Async data processing so that calls can be made to the bot"""
        request = data.decode(errors="ignore")
        headers = request.split("\r\n")
        matches = RedirectReceiver.REQUEST_LINE_RE.fullmatch(headers[0])
        if matches is None:
            self.send_response("Invalid request<br>Pls no hak me 😢", "400 no 👎")
            return

        authorization_code = matches[1]
        state = matches[2]
        logger.info(f"Auth: {state=} {authorization_code[:10]}")
        try:
            self.send_response(await verify_member(state, authorization_code))
        except Exception as e:
            logger.warning(f"Uncaught exception: {e} in verify")
            self.send_response("Invalid request 😢", "500 Woops")

    def send_response(self, message, status_code="200 OK"):
        """Send an HTML formatted response"""
        full_message = (
            """<!DOCTYPE html>
<html lang="en">
<head>
    <title>DSU Verification</title>
    <style>
        body {
            background: #004165;
        }

        .center {
            position: absolute;
            left: 50%;
            top: 30%;
            transform: translate(-50%, -50%);
            text-align: center;
            color: #ffffff;
        }

        .center > * {
            margin: 0;
        }

        #main {
            background: #ADAFAF;
            border-radius: 10px;
            padding: 15px;
        }
    </style>
</head>
<body>
<div class="center" id="main"><h1>"""
            + f"{message}"
            + """</h1></div></body></html>"""
        )
        http_response = f"HTTP/1.1 {status_code}\r\n"
        http_response += f"Server: DefSecAuthBot/2.0 Python/3\r\n"
        http_response += f"Content-Type: text/html; charset=utf-8\r\n"
        http_response += f"Root-Password: Password1!\r\n"
        http_response += f"Content-Length: {len(full_message)}\r\n"
        http_response += "\r\n"
        http_response += full_message

        # noinspection PyUnresolvedReferences
        self.transport.write(http_response.encode("UTF-8"))
        self.transport.close()


with open("creds.json") as c:
    creds = load(c)
oauth = AzureOauth(
    client_id=creds["oauth"]["client_id"],
    secret=creds["oauth"]["client_secret"],
    scopes=["openid+User.Read"],
    redirect_uri="https://auth.defsec.club/azure/auth",
)

dbc = DBC(host=creds["db"]["host"], user=creds["db"]["user"], password=creds["db"]["password"], db=creds["db"]["db"])
bot.run(creds["token"])
