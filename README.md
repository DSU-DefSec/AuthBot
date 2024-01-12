## Authbot
Verify and link discord members to O365 via Oauth. Additionally, sets roles based on the rank of the O365 account (student/faculty) and enforces realname. Must be manually overridden by admin to change name.



Install Requirements
```
apt install python3-pip python3-venv mariadb-server
mysql_secure_installation
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Initialize the DB

```
CREATE USER discord@localhost IDENTIFIED BY '';
CREATE DATABASE discord;
GRANT ALL PRIVILEGES ON discord.* to discord@localhost;
FLUSH PRIVILEGES;
```

Setup the config files
(config.json
creds.json)

Setup service

```
cp authbot.service /etc/systemd/system/authbot.service
systemctl start authbot
```
