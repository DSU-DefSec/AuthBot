#!/usr/bin/python
from json import load
from random import random, choice as rand_choice
from re import compile as re_compile
from string import ascii_letters, digits

import asyncio
import discord
import pymysql
from datetime import datetime
from discord.ext import commands
from discord.iterators import MemberIterator
from typing import Union

from utils import get_name, get_position, send_email

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())


async def db_login():
    with open("db.json", 'r') as c: db_creds = load(c)
    db = pymysql.connect(host=db_creds["host"], user=db_creds["user"], password=db_creds["password"],
                         db=db_creds["db"])
    return db, db.cursor()


async def db_save_close(db, cursor):
    if cursor is not None:
        cursor.close()
    if db is not None:
        db.commit()
        db.close()


async def init_db():
    db = None
    cursor = None
    try:
        db, cursor = await db_login()
        cursor.execute("SELECT VERSION()")
        data = cursor.fetchone()
        print(f"MySQL Version: {data[0]}")
        cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        id         BIGINT(18)                                                 NOT NULL
            PRIMARY KEY,
        discordTag VARCHAR(64)                                                NOT NULL,
        email      VARCHAR(64)                                                NULL,
        NAME       VARCHAR(64)                                                NULL,
        POSITION   ENUM ('non-dsu', 'student', 'professor') DEFAULT 'non-dsu' NOT NULL,
        CONSTRAINT email
            UNIQUE (email));""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS verify (
    email VARCHAR(50) NOT NULL,
    userid BIGINT(18) NOT NULL,
    code INT(6) NOT NULL,
    bigcode CHAR(16) NOT NULL,
    TIME TIMESTAMP NOT NULL,
    CONSTRAINT verify_users_id_fk FOREIGN KEY (userid) REFERENCES users (id) ON UPDATE CASCADE ON DELETE CASCADE)""")
        # cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS users_email_uindex ON users (email)""")
    except Exception as e:
        print(e)
        print("Error! Could not login to db")
        exit()
    finally:
        await db_save_close(db, cursor)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await init_db()
    bot.loop.create_task(start_websocket())
    # guild: discord.Guild = await bot.fetch_guild(757997063689470022)
    guilds = bot.guilds
    known_users = []
    for guild in guilds:
        print(guild)
        members: MemberIterator = guild.fetch_members(limit=None)
        try:
            while True:
                member = await members.next()
                if member.id not in known_users:
                    known_users.append(member.id)
                    await add_user_to_db(member)
        except discord.errors.NoMoreItems:
            pass
    print(f"Users: {len(known_users)}")


async def verification_message(message: discord.Message):
    """
    :param message:
    :return:
    """
    message.channel.typing()
    await add_user_to_db(message.author)

    email_re = re_compile(r'\w+\.\w+@(trojans\.|pluto\.)?dsu\.edu')
    code_re = re_compile(r'\d{6}')

    channel: discord.TextChannel = message.channel
    author: discord.Member = message.author
    message_response = None
    message_react = None

    email_address = email_re.search(message.content)
    email_address = email_address.group(0) if email_address else None

    verification_code = code_re.search(message.content)
    verification_code = verification_code.group(0) if verification_code else None

    if email_address:  # User sent an email
        print(f"Request to verify {email_address}")
        db, cursor = await db_login()
        cursor.execute(
            "SELECT TIME FROM verify WHERE email = %s AND TIME BETWEEN (DATE_SUB(NOW(), INTERVAL 10 MINUTE)) AND NOW() ORDER BY TIME DESC LIMIT 1",
            email_address)
        if cursor.rowcount == 0:
            code = str(int(random() * 999999 + 1000000))[1:]
            big_code = ''.join(rand_choice(ascii_letters + digits) for _ in range(16))
            req_id = ''.join(rand_choice(ascii_letters + digits) for _ in range(5))
            cursor.execute("INSERT INTO verify (email, userid, code, bigcode) VALUES (%s, %s, %s, %s)",
                           (email_address, author.id, code, big_code))
            big_code = f"https://api.mxsmp.com/dsu/verify.php?user={author.id}&code={big_code}"
            await send_email(email_address, str(author), code, big_code, req_id)
            message_react = "📧"
            message_response = f"Check your email for an email from DSU Auth Bot (matrixcraft.us@gmail.com)! ID: {req_id}\nCode valid for the next 30 minutes"
        else:
            message_react = "⚠"
            message_response = "Email sent too recently! Wait a few minutes before requesting another verification code."
        await db_save_close(db, cursor)
    elif verification_code:
        print(f"Request to verify {verification_code}")
        db, cursor = await db_login()
        cursor.execute(
            "SELECT code,email FROM verify WHERE userid = %s AND TIME BETWEEN (DATE_SUB(NOW(), INTERVAL 30 MINUTE)) AND NOW()",
            author.id)
        for r in cursor.fetchall():
            if r[0] == int(verification_code):
                try:
                    await verify_member(author, r[1])
                except:
                    pass
                await message.add_reaction("✅")
                break
        else:
            message_react = "❌"
            message_response = "Expired or invalid code"
        await db_save_close(db, cursor)
    else:
        print(f"Could not verify: {message.content}")
        message_react = "❌"
        message_response = "Bad email format!"
    if message_react: await message.add_reaction(message_react)
    await message.delete(delay=10)
    if message_response: await (await channel.send(message_response)).delete(delay=15)


async def add_user_to_db(user: Union[discord.User, discord.Member]):
    db, cursor = await db_login()
    username = str(user)
    cursor.execute(
        "INSERT INTO discord.users (id, discordTag) VALUES (%s, %s) ON DUPLICATE KEY UPDATE discordTag = %s;",
        (user.id, username, username))
    await db_save_close(db, cursor)


@bot.event
async def on_member_join(member: discord.Member):
    print(f"+{member} in {member.guild}")
    await add_user_to_db(member)


async def start_websocket():
    server = await asyncio.start_server(handle_socket_connection, "127.0.0.1", 8888)
    print(f"Listening on {server.sockets[0].getsockname()}")
    async with server: await server.serve_forever()


async def handle_socket_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info('peername')
    # print(f"Got connection on {addr}")
    data = await reader.read(100)
    message = data.decode()
    writer.close()
    print(f"Received {message!r} from {addr}")
    message = message.split(':')
    if len(message) != 2:
        print("Invalid data recieved")
        return
    uid = int(message[0])
    email = message[1]
    member: discord.Member = await bot.get_guild(757997063689470022).fetch_member(uid)
    await verify_member(member, email)


async def verify_member(member: discord.Member, email: str):
    if email == "?":
        print(f"ERROR verifying {member}")
        return
    db, cursor = await db_login()
    username = str(member)
    name = get_name(email)
    position = get_position(email)
    cursor.execute("REPLACE INTO discord.users (id, discordTag, email, name, position) VALUES (%s, %s, %s, %s, %s)",
                   (member.id, username, email, name, position))
    await db_save_close(db, cursor)
    await bot.get_channel(763544606369382403).send(
        f"{position.capitalize()} {name} email {email} linked {member.mention}")
    await member.add_roles(member.guild.get_role(758029400728928378), reason=f"Verified to {name} ({email})")
    try:
        await member.edit(nick=get_name(email), reason=f"Verified to {name} {email}")
    except discord.errors.Forbidden as e:
        print(e)
        pass
    with open("verify.log", "a") as log:
        log.write(f"{datetime.now()} {member} ({member.id}) => {email}\n")
    print(f"Verified {member} ({member.id}) to {email}")


@bot.event
async def on_message(message: discord.Message):
    # print(f"{message.channel} {message.author} >> {message.content}")

    await bot.process_commands(message)
    if message.author == bot.user:
        return
    if message.channel.id == 758030075328463081:
        await verification_message(message)


# @bot.command(pass_context=True)
# @commands.has_permissions(administrator=True)
# async def acommand(ctx, argument):
#     await ctx.say(f"Hi {argument}")


with open("creds.json", 'r') as c: creds = load(c)
bot.run(creds["token"])
