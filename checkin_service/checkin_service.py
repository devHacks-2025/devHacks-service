import json
import logging
import time
import os

from enum import Enum
from flask import Flask, request
from flask_cors import CORS
from notion_client import Client, APIResponseError, APIErrorCode

notion = Client(auth=os.environ["NOTION_KEY"], log_level=logging.DEBUG)
timeout = 1
app = Flask(__name__)
gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(logging.DEBUG)
CORS(app)

class Day(Enum):
    FRIDAY = "Friday"
    SATURDAY = "Saturday"

class Meal(Enum):
    LUNCH = "Lunch"
    DINNER = "Dinner"


@app.route("/api/v25/checkin", methods=["POST"])
def check_in_attendee():
    info = request.get_json()
    app.logger.debug(info)
    
    ticket_code = info.get("ticketCode", None)
    day = info.get("day", None)
    try:
        day_enum = Day(day)
    except ValueError:
        return "Invalid Day", 400

    meal = info.get("meal", None)
    meal_enum = None
    try:
        if meal is not None:
            meal_enum = Meal(meal)
    except ValueError:
        return "Invalid Meal", 400
    if not ticket_code or not day_enum:
        return "Bad Request", 400
    elif meal_enum:
        checkin_result = verify(ticket_code, day_enum, meal_enum)
        if checkin_result["success"]:
            return checkin_result["status"], 200
        elif checkin_result["warning"]:
            return checkin_result["status"], 250
        else:
            return checkin_result["status"], 400
    else:
        checkin_result = checkin(ticket_code, day_enum)
        if not checkin_result["success"]:
            return checkin_result["status"], 400
        else:
            return checkin_result["status"], 200

@app.route("/api/v25/checkin/<ticket_code>", methods=["GET"])
def get_attendee(ticket_code):
    attendee = get_ticket(ticket_code)
    if attendee:
        return attendee
    else:
        return "Not Found", 404


def checkin(ticket_id: str, day: Day):
    ticket = get_ticket(ticket_id)

    rate_limited = True

    return_val = {"success": False}

    if ticket:
        return_val["ticket"] = ticket
        is_checked_in = ticket["properties"][f"Checked In"]["checkbox"]
        first_name = ticket['properties']['First Name']['rich_text'][0]['plain_text']
        last_name = ticket['properties']['Last Name']['rich_text'][0]['plain_text']

        if not is_checked_in:
            while rate_limited:
                r = checkin_notion_request(ticket["id"])

                if r["object"] and not r["object"] == "error":
                    print(json.dumps(r, indent=4, sort_keys=True))
                    print(f"Successfully checked in {first_name} {last_name} with ticket {ticket_id}!")
                    return_val[
                        "status"] = f"Successfully checked in {first_name} {last_name} with ticket {ticket_id} for {day.value}!"
                    return_val["success"] = True
                    rate_limited = False
                elif r.get("object") == "error" and r.get("status") == 429:
                    print(f"Rate Limited - Retrying in {timeout} second(s)...")
                    time.sleep(timeout)
                else:
                    print(
                        f"Something went wrong trying to check in {first_name} {last_name} - {r.get('status', 400)} {r.get('message', '')}")
                    return_val[
                        "status"] = f"Something went wrong trying to check in {first_name} {last_name} - {r.get('status', 400)} {r.get('message', '')}!"

                    rate_limited = False
        else:
            return_val["status"] = f"{first_name} {last_name} is already checked in on {day.value}!"
            print(f"{first_name} {last_name} is already checked in!")
    else:
        return_val["status"] = f"{ticket_id} is an invalid ticket code. Please check the Notion Page."
        return_val["ticket"] = None
    return return_val

def verify(ticket_id: str, day: Day, meal: Meal):
    ticket = get_ticket(ticket_id)
    rate_limited = True
    return_val = {"success": False, "warning": False}

    if not ticket:
        return_val["status"] = f"{ticket_id} is an invalid ticket code. Please check the Notion Page."
        return_val["ticket"] = None
    else:
        return_val["ticket"] = ticket
        is_checked_in = ticket["properties"][f"{day.value} {meal.value} Verified"]["checkbox"]
        first_name = ticket['properties']['First Name']['rich_text'][0]['plain_text']
        last_name = ticket['properties']['Last Name']['rich_text'][0]['plain_text']

        if is_checked_in:
            msg = f"{first_name} {last_name} has already claimed {day.value} {meal.value}!"
            return_val["status"] = msg
            print(msg)
        else:
            while rate_limited:
                r = checkin_meal_notion_request(ticket["id"], day, meal)

                if r["object"] and not r["object"] == "error":
                    print(json.dumps(r, indent=4, sort_keys=True))
                    print(f"Successfully redeemed {first_name} {last_name} with ticket {ticket_id}!")
                    return_val[
                        "status"] = f"Successfully redeemed {first_name} {last_name} with ticket {ticket_id} for {day.value} {meal.value}!"
                    return_val["success"] = True
                    rate_limited = False
                elif r.get("object") == "error" and r.get("status") == 429:
                    print(f"Rate Limited - Retrying in {timeout} second(s)...")
                    time.sleep(timeout)
                else:
                    print(
                        f"Something went wrong trying to check in {first_name} {last_name} - {r.get('status', 400)} {r.get('message', '')}")
                    return_val[
                        "status"] = f"Something went wrong trying to redeem {first_name} {last_name} - {r.get('status', 400)} {r.get('message', '')}!"

                    rate_limited = False
    return return_val

def checkin_notion_request(page_id):
    return notion.pages.update(page_id, properties={ 'Checked In': { 'checkbox': True }})

def checkin_meal_notion_request(page_id, day, meal):
    return notion.pages.update(page_id, properties={f'{day.value} {meal.value} Verified': { 'checkbox': True }})

def get_ticket(ticket_id):
    while True:
        try:
            result = notion.databases.query(os.environ["NOTION_DATABASE_ID"],
                filter={
                    "property": "Ticket ID",
                    "rich_text": {
                        "contains": ticket_id
                    }
                },
                page_size=1
            )

            data = result.get("results", [])
            if len(data) == 0:
                return None
            return data[0]
        except APIResponseError as error:
            if error.code == APIErrorCode.RateLimited:
                wait_time = result.headers.get("Retry-After")
                time.sleep(wait_time)
            else:
                return None

if __name__ == "__main__":
    app.run()