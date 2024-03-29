#!/usr/bin/python
import asyncio
import base64
import json
import logging
from datetime import datetime
from re import compile as re_compile

import discord

from defsec_api import DefSecApi
from util import AzureOauth, DBC, Config, get_position, UrlButton, BasicTextInput, get_vapp_url_from_id

logging.basicConfig(filename="run.log")
logger = logging.getLogger("authbot")
logger.setLevel(logging.INFO)


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
        """Honesty, I have no clue but it doesnt work without this function"""
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
            self.send_response(await bot.verify_member(state, authorization_code))
        except Exception as e:
            logger.warning(f"Uncaught exception: {e} in verify")
            self.send_response("Invalid request 😢", "500 Oopsy Woopsy")

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
        http_response += "Server: DefSecAuthBot/2.0 Python/3\r\n"
        http_response += "Content-Type: text/html; charset=utf-8\r\n"
        http_response += "Root-Password: Password1!\r\n"
        http_response += f"Content-Length: {len(full_message)}\r\n"
        http_response += "\r\n"
        http_response += full_message

        # noinspection PyUnresolvedReferences
        self.transport.write(http_response.encode("UTF-8"))
        self.transport.close()


class HelpForm(discord.ui.Modal):
    """Simple help form that goes to admin"""

    def __init__(self):
        super().__init__(title="Assistance form")
        self.what = discord.ui.TextInput(
            label="How can we help you today?",
            custom_id="what",
            max_length=100,
            min_length=5,
        )
        self.add_item(self.what)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.command_failed:
            return
        await interaction.response.send_message(content="Received!", ephemeral=True)
        await bot.get_channel(1072935617719189626).send(
            embed=discord.Embed(
                title=f"Help request from {interaction.user.mention} ({interaction.user.id})",
                description=f"{self.what.value}",
            )
        )


class DeployButtonView(discord.ui.View):
    """View with deploy button"""

    def __init__(self, template_id: str, template_name: str = None):
        super().__init__(timeout=None)
        self.add_item(DeployButton(template_id, template_name))


class DeployButton(
    discord.ui.Button  # discord.ui.dynamic.DynamicItem[discord.ui.Button],
    # template=r"deploybutton:(?P<id>[a-zA-Z0-9-]{36})",
):
    """Button to deploy a vapp"""

    def __init__(self, template_id: str, template_name: str = None):
        super().__init__(
            label=f"Click for vapp ({template_name})",
            style=discord.ButtonStyle.blurple,
            custom_id="deploybutton:",
        )
        self.template_id = template_id
        self._embed_lock = asyncio.Lock()

    # @classmethod
    # async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
    #     return cls(template_id=match["id"])

    async def callback(self, interaction: discord.Interaction):
        """Respond to button press"""
        user = await bot.dbc.get_user(interaction.user.id)

        if user.email is None:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                content="You must be verified to do this! `/verify`", ephemeral=True
            )
            return

        if user.ialab_username is None:
            username = user.email.split("@")[0].lower()
            if await defsecapi.is_valid_user(username):
                await bot.dbc.update_ialab_username(interaction.user.id, username)
                await self.deploy_it(interaction, username)
                return

        if not await defsecapi.is_valid_user(user.ialab_username):
            # noinspection PyUnresolvedReferences
            await interaction.response.send_modal(
                BasicTextInput(
                    title="IALab username",
                    prompt="Username (https://ialab.dsu.edu)",
                    placeholder="Your username for ialab.dsu.edu",
                    max_length=50,
                    validator=defsecapi.is_valid_user,
                    callback=self.update_user,
                    error_message="No account found for `{}`",
                )
            )
        else:
            await self.deploy_it(interaction, user.ialab_username)

    async def update_user(self, interaction: discord.Interaction, username: str):
        """Set the user's IALab username from modal response"""
        await bot.dbc.update_ialab_username(interaction.user.id, username)
        await self.deploy_it(interaction, username)

    async def update_embed(self, interaction: discord.Interaction):
        """Add the user's name to the embed"""
        async with self._embed_lock:
            message: discord.Message = await interaction.message.fetch()
            e = message.embeds[0]
            if e.description is None:
                e.description = ""
            if interaction.user.mention not in e.description:
                e.description += f"\n +  {interaction.user.mention}"
            await message.edit(embed=e)

    async def deploy_it(self, interaction: discord.Interaction, username: str):
        """Deploy the vapp to the user"""
        asyncio.create_task(self.update_embed(interaction))
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True, thinking=True)
        vapp_url = await defsecapi.deploy_lesson(username, template_id=self.template_id)
        await interaction.followup.send(view=UrlButton(label="Your vapp is ready", url=vapp_url), ephemeral=True)


class AuthBot(discord.Client):
    def __init__(self, *, intents: discord.Intents, oauth: AzureOauth, dbc: DBC, config: Config, webserver_port: int):
        super().__init__(intents=intents)
        self.oauth = oauth
        self.dbc = dbc
        self.config = config
        self.webserver_port = webserver_port

        self.tree = discord.app_commands.CommandTree(self)

    @classmethod
    def create_from_creds(cls, creds: dict):
        """Create an instance of the bot from a creds dict"""
        instance = cls(
            intents=discord.Intents.all(),
            oauth=AzureOauth(
                client_id=creds["oauth"]["client_id"],
                secret=creds["oauth"]["client_secret"],
                scopes=["openid+User.Read"],
                redirect_uri="https://auth.defsec.club/azure/auth",
            ),
            dbc=DBC(
                host=creds["db"]["host"],
                user=creds["db"]["user"],
                password=creds["db"]["password"],
                db=creds["db"]["db"],
            ),
            config=Config("config.json"),
            webserver_port=int(creds["webserver_port"]),
        )

        async def command_deploy_autocompletion(
            interaction: discord.Interaction, current: str
        ) -> list[discord.app_commands.Choice[str]]:
            data = []
            if len(current) < 2:
                return data
            for vapp in list((await defsecapi.get_templates(partial=current, catalog=None)).keys()):
                data.append(discord.app_commands.Choice(name=vapp, value=vapp))
                if len(data) > 24:
                    break
            return data

        async def command_lesson_autocompletion(
                interaction: discord.Interaction, current: str
        ) -> list[discord.app_commands.Choice[str]]:
            data = []
            if len(current) < 2:
                return data
            for vapp in list((await defsecapi.get_lessons(current)).keys()):
                data.append(discord.app_commands.Choice(name=vapp, value=vapp))
                if len(data) > 24:
                    break
            return data

        async def command_share_autocompletion(
                interaction: discord.Interaction, current: str
        ) -> list[discord.app_commands.Choice[str]]:
            user = await bot.dbc.get_user(interaction.user.id)

            if user.ialab_username is None:
                return [discord.app_commands.Choice(name="Please /verify first", value="")]

            data = []
            if len(current) < 2:
                return data
            for name, vapp_id in list((await defsecapi.get_vapps_for_owner(current, user.ialab_username)).items()):
                data.append(discord.app_commands.Choice(name=name, value=name))
                if len(data) > 64:
                    break
            return data

        @instance.tree.command(name="deploy", description="Make a vapp deploy button")
        @discord.app_commands.autocomplete(template=command_deploy_autocompletion)
        async def command_deploy(interaction: discord.Interaction, template: str) -> None:
            """/deploy <template>"""
            if (template_id := await defsecapi.get_template_id(template)) is not None:
                logger.info(f"Deploy button for {template} by {interaction.user}")
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(
                    embed=discord.Embed(title="Who wants a vapp?"),
                    view=DeployButtonView(template_id, template),
                )
            else:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(content=f"Unknown template `{template}`!", ephemeral=True)

        @instance.tree.command(name="verify", description="Verify to a DSU account")
        async def command_verify(interaction: discord.Interaction) -> None:
            """/verify"""
            user = interaction.user
            await instance.dbc.add_user(user)
            session = await instance.dbc.init_oauth_session(user.id)
            oauth_url = instance.oauth.request(session)
            user_obj = await instance.dbc.get_user(user.id)
            logger.info(f"Auth request from: {user} {user_obj if user_obj.email is not None else ''}")
            if user_obj.email is not None:
                await instance.confirm_roles(interaction.user)
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title=f"You are already verified to {user_obj.name} ({user_obj.email})",
                        description=f"If you would like to verify again [Click here]({oauth_url})",
                    ),
                    ephemeral=True,
                )
            else:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(
                    view=UrlButton(
                        oauth_url, label="Click here to verify", emoji=instance.get_emoji(753434796063064158)
                    ),
                    ephemeral=True,
                )


        @instance.tree.command(name="help", description="Get help from the officers")
        async def command_help(interaction: discord.Interaction) -> None:
            """/help"""
            # noinspection PyUnresolvedReferences
            await interaction.response.send_modal(HelpForm())

        @instance.tree.command(name="share", description="Share vapp with group")
        @discord.app_commands.autocomplete(vapp=command_share_autocompletion)
        async def command_share(interaction: discord.Interaction, vapp: str, who: discord.Role) -> None:
            """/share <vapp> <role>"""

            user = await bot.dbc.get_user(interaction.user.id)

            if user.ialab_username is None:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(
                    content="You must be verified to do this! `/verify`", ephemeral=True
                )
                return

            print(f"Request from {user.ialab_username} to share {vapp}")

            # vapp_id = None
            # if vapp.startswith("vapp-") and len(vapp) == 41:
            #     # This is inefficient
            #     if vapp in (await defsecapi.get_vapps_for_owner("", user.ialab_username)).values():
            #         vapp_id = vapp
            # else:
            vapp_id = (await defsecapi.get_vapps_for_owner(vapp, user.ialab_username)).get(vapp, None)

            if vapp_id is None:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(content=f"Unknown vapp `{vapp}`!", ephemeral=True)
                return

            logger.info(f"Sharing {vapp} with {who}")
            # noinspection PyUnresolvedReferences
            await interaction.response.defer(ephemeral=True, thinking=True)

            to_share = {member.mention: (await bot.dbc.get_user(member.id)).ialab_username for member in who.members}

            if await defsecapi.share_vapp(vapp_id, [iu for iu in to_share.values() if iu is not None]):
                await interaction.followup.send(
                    embed=discord.Embed(
                        title=f"{interaction.user.display_name} shared `{vapp}` with:",
                        description="\n".join(
                            f"{k}: {v if v is not None else '`not verified!`'}" for k, v in to_share.items()
                        ),
                    ),
                    view=UrlButton(label=f"{vapp}", url=get_vapp_url_from_id(vapp_id)),
                    ephemeral=False,
                )
            else:
                # noinspection PyUnresolvedReferences
                await interaction.followup.send_message(
                    content=f"Error sharing `{vapp}` with ```{to_share.values()}```!", ephemeral=True
                )

        @instance.tree.command(name="lesson", description="Deploy a lesson vapp")
        @discord.app_commands.autocomplete(template=command_lesson_autocompletion)
        async def command_deploy(interaction: discord.Interaction, template: str) -> None:
            """/lesson <template>"""
            if (template_id := (await defsecapi.get_lessons(template)).get(template, None)) is not None:
                logger.info(f"Deploy button for {template} by {interaction.user}")
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(
                    embed=discord.Embed(title="Click button to deploy lesson"),
                    view=DeployButtonView(template_id, template),
                    ephemeral=True,
                )
            else:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(content=f"Unknown template `{template}`!", ephemeral=True)

        # @instance.tree.command(name="deploy_team", description="Deploy vapp to a team")
        # @discord.app_commands.autocomplete(template=command_deploy_autocompletion)
        # async def command_deploy_team(
        #     interaction: discord.Interaction,
        #     template: str,
        #     team_name: str,
        #     members: discord.Member,
        # ) -> None:
        #     """/deploy_team deploy vapp to a team of users"""
        #     if (template_id := await defsecapi.get_template_id(template)) is not None:
        #         logger.info(f"Deploy button for {template} by {interaction.user}")
        #
        #         users = [await bot.dbc.get_user(m.id) for m in members]
        #         if None in users:
        #             await interaction.response.send_message(
        #                 embed=discord.Embed(
        #                     title="No IALab user set for:",
        #                     description="\n".join(members[i].mention for i, u in enumerate(users) if u is None),
        #                 ),
        #                 ephemeral=True,
        #             )
        #             return
        #
        #         await interaction.response.defer(ephemeral=True, thinking=True)
        #
        #         vapp_url = await defsecapi.deploy_team(team_name, users=users, template_id=template_id)
        #         await interaction.followup.send(view=UrlButton(label="Deployed!", url=vapp_url), ephemeral=True)
        #     else:
        #         # noinspection PyUnresolvedReferences
        #         await interaction.response.send_message(content=f"Unknown template `{template}`!", ephemeral=True)

        return instance

    async def on_ready(self):
        """
        Fired when the bot had fully loaded.
        Start webserver thread and get all users
        """
        logger.info(f"Logged in as {self.user}")

        server = await self.loop.create_server(lambda: RedirectReceiver(), "127.0.0.1", self.webserver_port)
        logger.info(f"Webserver listening on 127.0.0.1:{self.webserver_port}")
        self.loop.create_task(start_webserver(server))

        await self.tree.sync()

        # Add all known users to the db to get first contact time
        known_users = []
        for guild in self.guilds:
            logger.info(f"Initializing members in {guild}")
            async for member in guild.fetch_members(limit=None):
                if member.id not in known_users:
                    known_users.append(member.id)
                    await self.dbc.add_user(member)
        logger.info(f"Total users: {len(known_users)}")

    async def on_member_join(self, member: discord.Member) -> None:
        """Fired when a member joins a server"""
        logger.info(f"+{member} in {member.guild}")
        await self.dbc.add_user(member)
        await self.confirm_roles(member)

    async def confirm_roles(self, member: discord.Member) -> None:
        """
        Check the user's nick and roles and confirm that they are correct.
        ** Roles are only added
        """
        if member is None:
            return
        user = await self.dbc.get_user(member.id)
        if user is None:
            logger.critical(f"Tried to verify null user {member} ({member.id})")
            return
        verify_reason = f"Verified to {user.name} ({user.email})"
        if user.name is not None:
            try:
                await member.edit(nick=user.name, reason=verify_reason)
            except discord.errors.Forbidden:
                logger.warning(f"Could not set nick for {member} on {member.guild}")
        try:
            if user.position == "professor":
                if (role_id := self.config.instructor_role(member.guild.id)) is not None:
                    if (role := member.guild.get_role(role_id)) is not None:
                        await member.add_roles(role, reason=verify_reason)

                if (role_id := self.config.instructor_role_remove(member.guild.id)) is not None:
                    if (role := member.guild.get_role(role_id)) is not None:
                        await member.remove_roles(role, reason=verify_reason)

            if user.position in ["student", "professor"]:
                if (role_id := self.config.student_role(member.guild.id)) is not None:
                    if (role := member.guild.get_role(role_id)) is not None:
                        await member.add_roles(role, reason=verify_reason)

                if (role_id := self.config.student_role_remove(member.guild.id)) is not None:
                    if (role := member.guild.get_role(role_id)) is not None:
                        await member.remove_roles(role, reason=verify_reason)

        except discord.errors.Forbidden:
            logger.warning(f"Could not set roles for {member} on {member.guild}")

    async def verify_member(self, state: str, code: str) -> str:
        """
        Verify an oauth response
        :param state: oauth state code
        :param code: oauth authorization code
        :return: Status message for user
        """
        user_id = await self.dbc.get_state_user_id(state)
        if user_id is None:
            return "Invalid or expired code 🙁"
        access_token = await self.oauth.get_access_token(code)
        if access_token is None:
            access_token = await self.dbc.get_access_token(code)
        if access_token is None:
            return "Invalid or expired code 🙁"
        # Not enough padding = :( Extra padding = :)
        user_info = json.loads(base64.b64decode(access_token.split(".")[1] + "===").decode())
        email = user_info["unique_name"]
        last_name, first_name = user_info["family_name"], user_info["given_name"]
        position = get_position(email)
        name = f"{first_name} {last_name}"
        username = self.get_user(int(user_id)).name

        await self.dbc.update_session(state, code=code, access_token=access_token)
        await self.dbc.update_user(user_id, email=email, name=name, position=position, username=username)

        with open("verify.log", "a") as log:
            log.write(f"{datetime.now()} {username} ({user_id}) => {email}\n")

        logger.info(f"Verified {username} ({user_id}) to {email}")
        for server_id, server in self.config.servers.items():
            try:
                member = self.get_guild(int(server_id)).get_member(int(user_id))
            except (ValueError, AttributeError):
                # User not in server
                continue
            await self.confirm_roles(member)
            try:
                if "verify_log" in server:
                    await self.get_channel(int(server["verify_log"])).send(
                        f"{position.capitalize()} {name} ({email}) linked {f'external: <@{user_id}>' if member is None else member.mention}"
                    )
            except (ValueError, AttributeError):
                logger.warning(f"Could not write to verify log channel {server.get('verify_log', '')} in {server_id}")
        return "Verified 👍"


with open("creds.json") as c:
    creds = json.load(c)

defsecapi = DefSecApi(host=creds["defsec_api"]["host"], api_key=creds["defsec_api"]["key"])
bot = AuthBot.create_from_creds(creds)
bot.run(creds["token"])
