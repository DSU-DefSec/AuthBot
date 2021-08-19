from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from json import load
from smtplib import SMTP


def get_name(email: str) -> str:
    return f"{email.split('.')[0].capitalize()} {email.split('@')[0].split('.')[1].capitalize()}"


# def get_username(user: discord.User) -> str:
#     return f"{user.name}#{str(user.discriminator).rjust(4, '0')}"


def get_position(email: str) -> str:
    if "@trojans.dsu.edu" in email.lower() or "@pluto.dsu.edu" in email.lower():
        return "student"
    if "@dsu.edu" in email:
        return "professor"
    return "non-dsu"


async def send_email(email_address: str, username: str, code: str, one_click_link: str, req_id: str) -> bool:
    name = get_name(email_address)
    with open("creds.json", 'r') as c: creds = load(c)
    with SMTP(creds["email"]["server"], creds["email"]["port"]) as mailServer:
        mailServer.starttls()
        mailServer.login(creds["email"]["email"], creds["email"]["password"])
        email = MIMEMultipart("alternative")
        email["To"] = "Our latest valued customer"
        email["From"] = "DSU Discord Auth Bot"
        email["Subject"] = "DSU Discord Verification"
        email.attach(MIMEText(f"""
            Welcome to the DSU Discord Server!
            Verifying will link you to @{username} and allow you to talk in voice/text channels.
            Our bot will set your nick name to {name}. If you would like to change your name please message an @Moderator
            By verifying you agree to follow the server rules: (https://server.rules/)
            - Be kind and respectful to others
            - No racism, sexism, homophobia or bigotry
            - No sexually explicit, offensive, illegal, or otherwise inappropriate profile pictures or nicknames
            - Do not spam
            - Keep content to its appropriate channels (memes in #memes, politics in #politics, etc...)
            - Observe the same behavior you would in any other school setting
            - Have fun

            To verify send code {code} in the #please-verify channel
            Or go to {one_click_link}

            Dont know how to use discord? https://tutorial.video/
            Questions? Message an @Moderator

            Thank you and have a great day!
            Didn't request this email? You are safe to delete it!
            Auth request ID: {req_id}""", "plain"))
        email.attach(MIMEText(f"""<html><body>
            <h2>Welcome to the DSU Discord Server!</h2>
            <p>Verifying will link you to <span style="background-color:#AFEEEE;">@{username}</span>&nbsp;and allow you to talk in voice/text channels.</p>
            <p>Our bot will set your nick name to <em>{name}</em>. If you would like to change your name please message an @Moderator</p>
            <p>By verifying you agree to follow the <a href="https://server.rules/">server rules</a></p>
            <ul>
                <li>Be kind and respectful to others</li>
                <li>No racism, sexism, homophobia or bigotry</li>
                <li>No sexually explicit, offensive, illegal, or otherwise inappropriate profile pictures or nicknames</li>
                <li>Do not spam</li>
                <li>Keep content to its appropriate channels (memes in #memes, politics in #politics, etc...)</li>
                <li>Observe the same behavior you would in any other school setting</li>
                <li>Have fun</li>
            </ul>
            <p>To accept the rules and verify your account click&nbsp;<a href="{one_click_link}">{one_click_link}</a></p>
            <p>Or&nbsp;send code&nbsp;<strong style="background-color: rgb(204, 204, 204);">{code}</strong>&nbsp;in the&nbsp;<span style="background-color: rgb(175, 238, 238);">#please-verify</span>&nbsp;channel</p>
            <p>Dont know how to use discord? <a href="https://tutorial.video/">Tutorial video</a></p>
            <p>Questions? Message an @Moderator</p>
            <p>Thank you and have a great day!</p>
            <p>Didn&#39;t request this email? You are safe to delete it!</p>
            <p>Auth request ID: {req_id}</p>
            </body></html>""", "html"))
        mailServer.sendmail(creds["email"]["email"], email_address, email.as_string())
    return True
