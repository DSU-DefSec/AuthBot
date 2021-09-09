from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from json import load
from smtplib import SMTP


def get_name(email: str) -> str:
    return f"{email.split('.')[0].capitalize()} {email.split('@')[0].split('.')[1].capitalize()}"


def get_position(email: str) -> str:
    if "@trojans.dsu.edu" in email.lower() or "@pluto.dsu.edu" in email.lower():
        return "student"
    if "@dsu.edu" in email:
        return "professor"
    return "non-dsu"


# def get_username(user: discord.User) -> str:
#     return f"{user.name}#{str(user.discriminator).rjust(4, '0')}"


def send_email(email_address: str, username: str, code: str, one_click_link: str) -> bool:
    name = get_name(email_address)
    with open("creds.json", "r") as c: creds = load(c)
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
            Didn't request this email? You are safe to delete it!""", "plain"))
        email.attach(MIMEText("""<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml">
<head>
  <meta charset="utf-8">
  <meta name="x-apple-disable-message-reformatting">
  <meta http-equiv="x-ua-compatible" content="ie=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings xmlns:o="urn:schemas-microsoft-com:office:office">
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <style>
    td,th,div,p,a,h1,h2,h3,h4,h5,h6 {font-family: "Segoe UI", sans-serif; mso-line-height-rule: exactly;}
  </style>
  <![endif]-->
    <title>Verify your Discord Account!</title>
    <style>
.hover-bg-indigo-700:hover {
  background-color: #4338ca !important;
}
</style>
</head>
<body style="margin: 0; width: 100%; padding: 0; word-break: break-word; -webkit-font-smoothing: antialiased; background-color: #ffffff;">
    <div style="display: none;">Welcome to the DSU Discord Server! Please verify your account!&#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &zwnj;
      &#160;&#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &#847; &zwnj;
      &#160;&#847; &#847; &#847; &#847; &#847; </div>
  <div role="article" aria-roledescription="email" aria-label="Verify your Discord Account!" lang="en">
    <div style="margin-left: auto; margin-right: auto; max-width: 820px; font-family: Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;">
      <div style="margin-left: auto; margin-right: auto; background-color: #f3f4f6; padding: 48px;">
        <h1 style="text-align: center; font-size: 48px; font-weight: 700;">Welcome to the DSU Discord&nbsp;Server!</h1>
        <div style="text-align: center;">
          <a class="hover-bg-indigo-700" href="#" style="display: inline-block; border-radius: 4px; background-color: #3730a3; padding-top: 16px; padding-bottom: 16px; padding-left: 24px; padding-right: 24px; text-align: center; font-size: 16px; font-weight: 600; color: #ffffff; text-decoration: none;">Click to verify</a>
          <div style="margin-top: 12px;">or send <span style="font-weight: 700;">1234</span> in #please-verify</div>
        </div>
        <ul style="list-style-position: inside; list-style-type: disc;">
          <li>You will be able to talk in our server</li>
          <li>This will link you to <code style="border-radius: 6px; background-color: #e5e7eb; padding: 0.25rem;">@Username#1234</code></li>
          <li>Your nickname will be set to <b>Gaelin Shupe</b>. <i>Contact a moderator to change it.</i></li>
          <li>You agree to the Server Rules</li>
        </ul>
      </div>
      <div style="padding: 48px;">
        <h2 style="font-size: 30px; font-weight: 700;">Server Rules</h2>
        <ul style="list-style-position: inside; list-style-type: disc;">
          <li>Be kind and respectful to others</li>
          <li>No racism, sexism, homophobia or bigotry</li>
          <li>No sexually explicit, offensive, illegal, or otherwise inappropriate profile pictures or nicknames</li>
          <li>Do not spam</li>
          <li>Keep content to its appropriate channels (memes in #memes, politics in #politics, etc...)</li>
          <li>Observe the same behavior you would in any other school setting</li>
          <li>Have fun</li>
        </ul>
      </div>
      <div style="display: block; background-color: #f3f4f6; padding: 48px;">
        <div>Don't know how to use discord? Check out <a href="#" style="text-decoration: underline;">this tutorial</a>!</div>
        <div style="margin-top: 8px;">Questions? Comments? Concerns? Contact a @Moderator</div>
        <div style="margin-top: 8px;">Didn't request this email? Feel free to delete it!</div>
        <div style="margin-top: 8px; color: #6b7280;">Auth request ID: <span style="font-weight: 700;">1439985</span></div>
      </div>
    </div>
  </div>
</body>
</html>""", "html"))
        mailServer.sendmail(creds["email"]["email"], email_address, email.as_string())
    return True
