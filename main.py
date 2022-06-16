#!/usr/bin/python
import asyncio
import json
from datetime import datetime
from json import load
from random import random, choice as rand_choice
from re import compile as re_compile
from string import ascii_letters, digits

import discord
import pymysql
from discord.ext import commands
from discord.iterators import MemberIterator

from utils import get_name, get_position, send_email

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
bot.cursor = None
bot.db = None
bot.config = None
bot.auth_channels = None
EMAIL_RE = re_compile(r"\w{0,23}\.\w{0,23}@(trojans\.|pluto\.)?dsu\.edu")
CODE_RE = re_compile(r"\d{6}")


def reload_config():
    bot.config = json.load(open("config.json"))["servers"]
    bot.auth_channels = [str(bot.config[server].get("verify_channel", "")) for server in bot.config]
    print("Loaded server config")


reload_config()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    bot.loop.create_task(start_websocket())
    known_users = []

    with open("creds.json", "r") as c:
        db_creds = load(c)["db"]
    bot.db = pymysql.connect(
        host=db_creds["host"],
        user=db_creds["user"],
        password=db_creds["password"],
        db=db_creds["db"],
        autocommit=True
    )
    bot.cursor = bot.db.cursor()
    bot.cursor.execute("""CREATE TABLE IF NOT EXISTS users (
id           BIGINT(20)                                                                  NOT NULL PRIMARY KEY,
discordTag   VARCHAR(40)                                                                 NOT NULL,
email        VARCHAR(64)                                                                 NULL,
NAME         VARCHAR(64)                                                                 NULL,
POSITION     ENUM ('non-dsu', 'student', 'professor', 'unverified') DEFAULT 'unverified' NOT NULL,
verifyDate   TIMESTAMP                                                                   NULL,
verifyServer BIGINT(20)                                                                  NULL,
CONSTRAINT email UNIQUE (email));""")
    bot.cursor.execute("""CREATE TABLE IF NOT EXISTS verify (
email   VARCHAR(64)                           NOT NULL,
userid  BIGINT                                NOT NULL,
code    INT(6)                                NOT NULL,
bigcode CHAR(16)                              NOT NULL,
TIME    TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL ON UPDATE CURRENT_TIMESTAMP(),
CONSTRAINT userid FOREIGN KEY (userid) REFERENCES discord.users (id) ON UPDATE CASCADE ON DELETE CASCADE);""")

    for guild in bot.guilds:
        print(guild)
        members: MemberIterator = guild.fetch_members(limit=None)
        try:
            while True:
                member = await members.next()
                if member.id not in known_users:
                    known_users.append(member.id)
                    add_user_to_db(member)
        except discord.errors.NoMoreItems:
            pass
    bot.db.commit()
    print(f"Users: {len(known_users)}")


async def verification_message(message: discord.Message):
    """
    :param message:
    :return:
    """
    if message.author.id == 230084329223487489:
        return
    add_user_to_db(message.author)

    author: discord.Member = message.author
    message_content = message.content.strip()

    email_address = addr.group() if (addr := EMAIL_RE.search(message_content)) else None
    verification_code = code.group() if (code := CODE_RE.search(message_content)) else None

    if email_address:  # User sent an email address
        print(f"Request to verify {email_address} in {message.guild}")

        if bot.cursor.execute(
                "SELECT TIME FROM verify WHERE email = %s AND TIME BETWEEN (DATE_SUB(NOW(), INTERVAL 5 MINUTE)) AND NOW() ORDER BY TIME DESC LIMIT 1",
                email_address) != -1:
            code = str(int(random() * 999999 + 1000000))[1:]
            big_code = "".join(rand_choice(ascii_letters + digits) for _ in range(16))
            # req_id = "".join(rand_choice(ascii_letters + digits) for _ in range(5))

            bot.cursor.execute(
                "INSERT INTO verify (email, userid, code, bigcode) VALUES (%s, %s, %s, %s)",
                (email_address, author.id, code, big_code)
            )
            big_code = f"https://dsu.gael.in/verify.php?user={author.id}&code={big_code}"
            try:
                send_email(email_address, str(author), code, big_code)
            except Exception as e:
                print(f"Exception with email {e}")
                await message.reply(
                    f"Error sending email to {email_address} ({message.author}). (<@230084329223487489>)"
                )
                await message.delete(delay=10)
                return
            message_react = "📧"
            message_response = f"Check your email (and spam folder) for a message from DSU Auth Bot!\nVerification code valid for the next hour"
        else:
            message_react = "⚠"
            message_response = "Email sent too recently! Wait a few minutes before requesting another verification code."

    elif verification_code:
        print(f"Request to verify {verification_code} in {message.guild}")
        if bot.cursor.execute(
                "SELECT code,email FROM verify WHERE userid = %s AND code = %s AND TIME BETWEEN (DATE_SUB(NOW(), INTERVAL 60 MINUTE)) AND NOW()",
                (author.id, int(verification_code))) > 0:
            r = bot.cursor.fetchone()
            message_react = "✅"
            message_response = f"Verified to {r[1]}!\nCheck out some of the other channels <#757997403570831503>"
            # await (await message.reply(message_response)).delete(delay=10)
            await verify_member(author.id, r[1])

        else:
            message_react = "❌"
            message_response = "Expired or invalid code"
    else:
        print(f"Could not verify: {message.content}")
        message_react = "❌"
        message_response = "Bad email format!"
    if message_react: await message.add_reaction(message_react)
    await message.delete(delay=25)
    if message_response: await (await message.reply(message_response)).delete(delay=25)


def add_user_to_db(member: discord.Member):
    username = str(member)
    bot.cursor.execute(
        "INSERT INTO discord.users (id, discordTag) VALUES (%s, %s) ON DUPLICATE KEY UPDATE discordTag = %s;",
        (member.id, username, username)
    )


async def confirm_roles(member: discord.Member):
    bot.cursor.execute("SELECT email,name,position FROM discord.users WHERE id = %s", member.id)
    user_info = bot.cursor.fetchone()
    if not user_info: return
    if user_info[1]:
        try:
            await member.edit(nick=user_info[1], reason=f"Verified to {user_info[1]} ({user_info[0]})")
        except discord.errors.Forbidden:
            pass
    try:
        if user_info[2] == "professor":
            await member.add_roles(
                member.guild.get_role(int(bot.config[str(member.guild.id)][f"instructor_role"])),
                reason=f"Verified to {user_info[1]} ({user_info[0]})"
            )
            await member.add_roles(
                member.guild.get_role(int(bot.config[str(member.guild.id)][f"student_role"])),
                reason=f"Verified to {user_info[1]} ({user_info[0]})"
            )
        if user_info[2] == "student":
            await member.add_roles(
                member.guild.get_role(int(bot.config[str(member.guild.id)][f"student_role"])),
                reason=f"Verified to {user_info[1]} ({user_info[0]})"
            )
    except (KeyError, TypeError, discord.errors.Forbidden):
        pass


@bot.event
async def on_member_join(member: discord.Member):
    print(f"+{member} in {member.guild}")
    bot.db.ping()
    add_user_to_db(member)
    bot.db.commit()
    await confirm_roles(member)


async def start_websocket():
    server = await asyncio.start_server(handle_socket_connection, "127.0.0.1", 8888)
    print(f"Listening on {server.sockets[0].getsockname()}")
    async with server: await server.serve_forever()


async def handle_socket_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    # print(f"Got connection on {addr}")
    data = await reader.read(100)
    message = data.decode()
    writer.close()
    print(f"Received {message!r} from {addr}")
    message = message.split(":")
    if len(message) != 3:
        print("Invalid data recieved")
        return
    uid = int(message[0])
    email = message[1]
    bot.db.ping()
    bot.cursor.execute(
        "SELECT email FROM verify WHERE bigcode = %s AND TIME BETWEEN (DATE_SUB(NOW(), INTERVAL 60 MINUTE)) AND NOW()",
        message[2]
    )
    if bot.cursor.fetchone()[0] != email:
        print("Code does not match")
        return
    await verify_member(uid, email)


async def verify_member(uid: int, email: str):
    if email == "?":
        print(f"ERROR verifying {uid}")
        return
    username = str(bot.get_user(uid))
    name = get_name(email)
    position = get_position(email)
    # Replacing the id kills the fk to verify thus deleting the pending verifications
    bot.cursor.execute(
        "REPLACE INTO discord.users (id, discordTag, email, name, position) VALUES (%s, %s, %s, %s, %s)",
        (uid, username, email, name, position)
    )
    with open("verify.log", "a") as log:
        log.write(f"{datetime.now()} {bot.get_user(uid)} ({uid}) => {email}\n")
    print(f"Verified {bot.get_user(uid)} ({uid}) to {email}")
    for server in bot.config:
        try:
            member = bot.get_guild(int(server)).get_member(uid)
            await confirm_roles(member)
            await bot.get_channel(int(bot.config[server]["verify_log"])).send(
                f"{position.capitalize()} {name} email {email} linked {member.mention}"
            )
        except (ValueError, AttributeError):
            pass


@bot.command(name="config")
@commands.has_permissions(administrator=True)
async def config(ctx):
    await ctx.send(embed=discord.Embed(
        title="Config for this server",
        description=f"""
Verify channel: <#{bot.config[str(ctx.guild.id)]["verify_channel"]}>
Verify log: <#{bot.config[str(ctx.guild.id)]["verify_log"]}>
Student Role: <@&{bot.config[str(ctx.guild.id)]["student_role"]}>
Professor Role: <@&{bot.config[str(ctx.guild.id)]["instructor_role"]}>
"""))


@bot.command(name="reloadconfig")
@commands.has_permissions(administrator=True)
async def reload(ctx):
    await ctx.message.delete(delay=2)
    reload_config()


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)
    if str(message.channel.id) in bot.auth_channels:
        with message.channel.typing():
            bot.db.ping()
            await verification_message(message)

    # @bot.command(pass_context=True)
    # @commands.has_permissions(administrator=True)
    # async def acommand(ctx, argument):
    #     await ctx.say(f"Hi {argument}")


with open("creds.json", "r") as c:
    creds = load(c)
bot.run(creds["token"])
