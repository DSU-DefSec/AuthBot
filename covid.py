import json
import os
from csv import reader as csv_reader

import pymysql
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Get DSU covid data
dsu_data = {}
try:
    soup = BeautifulSoup(requests.get("https://dsu.edu/covid-19.html").content, "html.parser")
    for cells in [table_row.find_all("td") for table_row in soup.find_all("tr")]:
        if len(cells) != 2: continue
        key = cells[0].text.strip(" \n")

        if key == "CURRENT ACTIVE CASES - EMPLOYEES ONLY":
            key = "employees"
        elif key == "CURRENT ACTIVE CASES - STUDENTS ONLY":
            key = "students"
        elif key == "CURRENT ACTIVE CASES - EMPLOYEES AND STUDENTS":
            key = "total"
        elif key == "CURRENT QUARANTINE/ISOLATION IN CAMPUS FACILITIES - EMPLOYEES AND STUDENTS":
            key = "quarantine_dsu"
        elif key == "CURRENT QUARANTINE/ISOLATION - EMPLOYEES AND STUDENTS (INCLUDING HOME QUARANTINE)":
            key = "quarantine"
        dsu_data[key] = cells[1].text
except Exception as e:
    print(e)
    print("Failed to get data")
    exit()
# Make sure db exists
with open(f"{os.path.dirname(__file__)}/db.json", 'r') as c: db_creds = json.load(c)
db = pymysql.connect(host=db_creds["host"], user=db_creds["user"], password=db_creds["password"],
                     db=db_creds["db"])
cursor = db.cursor()

# Confirm data since last push
cursor.execute("""CREATE TABLE IF NOT EXISTS covid (
    time           TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
    employees      INT                                   NOT NULL,
    students       INT                                   NOT NULL,
    total          INT                                   NOT NULL,
    quarantine_dsu INT                                   NOT NULL,
    quarantine     INT                                   NOT NULL);""")
cursor.execute("""SELECT employees, students, total, quarantine_dsu, quarantine FROM discord.covid
ORDER BY time DESC LIMIT 0;""")
last_row = cursor.fetchone()
if last_row is None or last_row[0] != dsu_data["employees"] or last_row[1] != dsu_data["students"] or last_row[2] != \
        dsu_data["total"] or last_row[3] != dsu_data["quarantine_dsu"] or last_row[4] != dsu_data["quarantine"]:
    # Commit new data to db
    cursor.execute("""INSERT INTO discord.covid (employees, students, total, quarantine_dsu, quarantine)
VALUES (%s, %s, %s, %s, %s)""", (
        dsu_data["employees"],
        dsu_data["students"],
        dsu_data["total"],
        dsu_data["quarantine_dsu"],
        dsu_data["quarantine"]))
    db.commit()
cursor.close()
db.close()

# Get World covid data
try:
    world_data = json.load(open(f"{os.path.dirname(__file__)}/covid_cache.json"))
except FileNotFoundError:
    world_data = {"CSSEGISandData": "2001-01-01T01:01:01", "govex": "2001-01-01T01:01:01", "US": {}, "world": {}}
today = datetime.now()
if today.month == 1:
    last_month = today.replace(year=today.year - 1, month=12)
else:
    last_month = today.replace(month=today.month - 1)
last_year = today.replace(year=today.year - 1)


def parse_csv(url: str, form2: bool = False) -> dict:
    """
    Parses the csv data from a url. Uses the specific format from the 3 links
    :param url: duh
    :param form2: if from govex
    :return: the data but better
    """
    csv_parser = csv_reader(requests.get(url).text.split("\n"))
    csv_data = []
    us_id = -1
    for row in csv_parser:
        if len(row) == 0: continue
        if len(csv_data) > 0 and (row[6] if form2 else row[0]) != "": continue
        if row[1] == "US":
            us_id = len(csv_data)
        csv_data.append(row)

    first = True
    world = {"month": 0, "year": 0, "all": 0}
    us = {"month": 0, "year": 0, "all": 0}
    for col in range(0, len(csv_data[0])):
        try:
            day = datetime.strptime(csv_data[0][col], "%Y-%m-%d" if form2 else "%m/%d/%y")
        except ValueError:
            continue
        daily_total = 0
        if first:
            for row in csv_data[1:]: daily_total += int(r if (r := row[col]) != "" else 0)
            daily_us = int(csv_data[us_id][col])
            first = False
        else:
            for row in csv_data[1:]:
                daily_total += int(r if (r := row[col]) != "" else 0) - int(r if (r := row[col - 1]) != "" else 0)
            daily_us = int(csv_data[us_id][col]) - int(csv_data[us_id][col - 1])

        world["all"] += daily_total
        us["all"] += daily_us
        if day > last_year:
            world["year"] += daily_total
            us["year"] += daily_us
        if day > last_month:
            world["month"] += daily_total
            us["month"] += daily_us
    return {"US": us, "world": world}


updated = False
resp = requests.get("https://api.github.com/repos/CSSEGISandData/COVID-19")
if datetime.fromisoformat(resp.json()["pushed_at"][:-1]) > datetime.fromisoformat(world_data["CSSEGISandData"]):
    world_data["CSSEGISandData"] = resp.json()["pushed_at"][:-1]
    cases = parse_csv(
        "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv"
    )
    world_data["US"]["cases"] = cases["US"]
    world_data["world"]["cases"] = cases["world"]
    deaths = parse_csv(
        "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_deaths_global.csv"
    )
    world_data["US"]["deaths"] = deaths["US"]
    world_data["world"]["deaths"] = deaths["world"]
    updated = True

resp = requests.get("https://api.github.com/repos/govex/COVID-19")
if datetime.fromisoformat(resp.json()["pushed_at"][:-1]) > datetime.fromisoformat(world_data["govex"]):
    world_data["govex"] = resp.json()["pushed_at"][:-1]
    vax = parse_csv(
        "https://raw.githubusercontent.com/govex/COVID-19/master/data_tables/vaccine_data/global_data/time_series_covid19_vaccine_doses_admin_global.csv",
        form2=True
    )
    world_data["US"]["vax"] = vax["US"]
    world_data["world"]["vax"] = vax["world"]
    updated = True

if updated:
    json.dump(world_data, open(f"{os.path.dirname(__file__)}/covid_cache.json", "w"))

data_template = "{d[cases][month]:,}\n{d[cases][year]:,}\n{d[cases][all]:,}\n\n**{country}**\n{d[deaths][month]:,}\n{d[deaths][year]:,}\n{d[deaths][all]:,}\n\n**{country}**\n{d[vax][month]:,}\n{d[vax][year]:,}\n{d[vax][all]:,}"
old = {
    "title": "World Wide Covid Data",
    "url": "https://www.arcgis.com/apps/dashboards/bda7594740fd40299423467b48e9ecf6",
    "color": 16711680,
    "fields": [
        {
            "name": "Cases",
            "value": "Rolling month\nRolling year\nAll time\n\n**Deaths**\nRolling month\nRolling year\nAll time\n\n**Vaccination Doses**\nRolling month\nRolling year\nAll time",
            "inline": True
        },
        {
            "name": "US",
            "value": data_template.format(d=world_data["US"], country="US"),
            "inline": True
        },
        {
            "name": "World",
            "value": data_template.format(d=world_data["world"], country="World"),
            "inline": True
        }
    ],
    "footer": {
        "text": "Updated"
    },
    "timestamp": max(datetime.fromisoformat(world_data["govex"]),
                     datetime.fromisoformat(world_data["CSSEGISandData"])).isoformat()
}
message = {
    "embeds": [
        {
            "title": "World Wide Covid Data",
            "url": "https://www.arcgis.com/apps/dashboards/bda7594740fd40299423467b48e9ecf6",
            "color": 16711680,
            "description": """```yml
Cases:         {us:^{n1}}{world:^{n2}}
Rolling Month: {u[cases][month]:>{n1},} {w[cases][month]:>{n2},}
Rolling Year:  {u[cases][year]:>{n1},} {w[cases][year]:>{n2},}
All Time:      {u[cases][all]:>{n1},} {w[cases][all]:>{n2},}

Deaths:        {us:^{n1}}{world:^{n2}}
Rolling Month: {u[deaths][month]:>{n1},} {w[deaths][month]:>{n2},}
Rolling Year:  {u[deaths][year]:>{n1},} {w[deaths][year]:>{n2},}
All Time:      {u[deaths][all]:>{n1},} {w[deaths][all]:>{n2},}

Vaccine Doses: {us:^{n1}}{world:^{n2}}
Rolling Month: {u[vax][month]:>{n1},} {w[vax][month]:>{n2},}
Rolling Year:  {u[vax][year]:>{n1},} {w[vax][year]:>{n2},}
All Time:      {u[vax][all]:>{n1},} {w[vax][all]:>{n2},}```""".format(u=world_data["US"], w=world_data["world"], n1=12,
                                                                      n2=14, us="US", world="World"),
            "footer": {
                "text": "Updated"
            },
            "timestamp": max(datetime.fromisoformat(world_data["govex"]),
                             datetime.fromisoformat(world_data["CSSEGISandData"])).isoformat()
        },
        {
            "title": "DSU Covid Dashboard",
            "url": "https://dsu.edu/covid-19.html",
            "color": 43488,
            "fields": [
                {
                    "name": "Total Active Cases",
                    "value": "Students\nEmployees\n\n**Total Quarantine**\nIn Campus Facilities",
                    "inline": True
                },
                {
                    "name": dsu_data["total"],
                    "value": "{d[students]}\n{d[employees]}\n\n**{d[quarantine]}**\n{d[quarantine_dsu]}".format(
                        d=dsu_data),
                    "inline": True
                }
            ],
            "footer": {
                "text": "Updated"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    ]
}

UPDATE_MESSAGE = "880234208327516181"
WEBHOOK = json.load(open(f'{os.path.dirname(__file__)}/creds.json'))['covid_webhook']
resp = requests.patch(f"{WEBHOOK}/messages/{UPDATE_MESSAGE}?wait=true", data=json.dumps(message),
                      headers={"Content-Type": "application/json"})
