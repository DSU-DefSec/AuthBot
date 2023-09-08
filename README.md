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
move authbot.service -> /etc/systemd/system/authbot.service
systemctl start authbot
```