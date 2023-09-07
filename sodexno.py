import datetime
import json
import os

import requests

date_string = datetime.date.today().strftime("%m/%d/%Y")
menu_link = f"https://menus.sodexomyway.com/BiteMenu/MenuOnly?menuId=15109&locationId=10344001&startDate={date_string}"
resp = requests.get(menu_link)
if "Sorry, no menu found" in resp.text:
    print("No menus for this week")
    exit()

week_menu = json.loads(resp.text.split("class='hide'>")[1].split("</div>")[0])
json.dump(week_menu, open(f"{os.path.dirname(__file__)}/sodexno.json", "w"))

message = {"embeds": []}

good_menu = {}
for day in week_menu:
    day_value = day["date"]
    if datetime.date.today().strftime("%Y-%m-%d") not in day_value:
        continue
    good_menu[day_value] = {}
    for part in day["dayParts"]:
        part_name = part["dayPartName"]
        good_menu[day_value][part_name] = {}
        fields = []
        for course in part["courses"]:
            course_name = course["courseName"]
            for t in ["DSU", "UNIV"]:
                course_name = course_name.replace(t, "")
            course_name = course_name.strip()
            if course_name in ["", "-", "SALAD BAR", "MISCELLANEOUS"]:
                continue
            good_menu[day_value][part_name][course_name] = {}
            item_text = ""
            for item in course["menuItems"]:
                item_name = item["formalName"]
                for t in ["(1 Oz)", ", 1/2 Oz", ", 6 Oz"]:
                    item_name = item_name.replace(t, "")
                if item_name == "":
                    continue
                item_text += f"\n -  {item_name.strip()}"
                # if item['calories'] != "" and item['calories'] != "0":
                #     item_text += f" *({item['calories']})*"
                # if item['description'] != "":
                #     item_text += f" ~ *{item['description']}*"
                good_menu[day_value][part_name][course_name][item_name] = item["description"]
            if item_text == "":
                continue
            fields.append({"name": course_name.capitalize(), "inline": True, "value": item_text})
        if part_name == "BREAKFAST":
            time_slot = "7:30am - 10:00am"
        elif part_name == "LUNCH":
            time_slot = "11:00am - 1:30pm"
        elif part_name == "AFTERNOON SNACK":
            time_slot = "1:30pm - 5:00pm"
        elif part_name == "DINNER":
            if datetime.date.today().weekday() == 6:
                time_slot = "5:00pm - 7:00pm"
            elif datetime.date.today().weekday() == 5:
                time_slot = "5:00pm - 6:30pm"
            else:
                time_slot = "5:00pm - 7:30pm"
        elif part_name == "BRUNCH":
            time_slot = "11:30am - 1:30pm"
        else:
            time_slot = ""

        message["embeds"].append(
            {
                "title": part_name.capitalize(),
                "url": f"https://menus.sodexomyway.com/BiteMenu/Menu?menuId=15109&locationId=10344001&whereami=https://dsu.sodexomyway.com/dining-near-me/trojan-marketplace?{len(message['embeds'])}",
                "fields": fields,
                "author": {"name": f"{datetime.date.today().strftime('%m/%d')}: {time_slot}"},
                "footer": {"text": "Cereal and Salad Bar are always available"},
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }
        )

UPDATE_MESSAGE = "880909341325144184"
WEBHOOK = json.load(open(f"{os.path.dirname(__file__)}/creds.json"))["sodexno_webhook"]
resp = requests.patch(
    f"{WEBHOOK}/messages/{UPDATE_MESSAGE}?wait=true",
    data=json.dumps(message),
    headers={"Content-Type": "application/json"},
)
