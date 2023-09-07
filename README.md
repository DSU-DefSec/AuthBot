```
apt install python3-pip python3-venv mariadb-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

mysql_secure_installation

CREATE USER discord@localhost IDENTIFIED BY '';
CREATE DATABASE discord;
GRANT ALL PRIVILEGES ON discord.* to discord@localhost;
FLUSH PRIVILEGES;

python3 main.py
```