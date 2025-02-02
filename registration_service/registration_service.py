import json
import logging
import smtplib
import sys
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import io
import jinja2
from flask_cors import CORS
import os

import requests as requests
import segno
from flask import Flask, request, Response, url_for
from attendee import Attendee
from notion_client import Client

DEVCLUB_EMAIL = "umdevclub@gmail.com"

app = Flask(__name__)
CORS(app)
env = json.load(open("../env.json"))
notion = Client(auth=env.get("NOTION_TOKEN"), log_level=logging.DEBUG)


@app.route('/')
def hello_world():
    return 'Hello World!'

@app.route('/api/v25/register', methods=["POST"])
def register():
    full_form_data = request.get_json()  # Webhook Data
    r = create_and_send_ticket(full_form_data)
    print(r)
    return r

@app.route('/api/v25/tickets/<ticket_id>', methods=["GET"])
def get_qr_code(ticket_id: str):
    qr = segno.make_qr(ticket_id)
    b = io.BytesIO()
    qr.save(b, kind="png", scale=6)
    return Response(b.getvalue(), mimetype='image/png')

# Registrants are stored as pages in a Notion database
@app.route('/api/v25/tickets/<notion_page_id>', methods=["POST"])
def resend_qr_code(notion_page_id):
    reg_page = notion.pages.retrieve(notion_page_id)
    print(json.dumps(reg_page.json(), indent=4))


    if reg_page.status_code == 404:
        return "404 ID Not Found", 404
    elif reg_page.status_code == 400 or reg_page.status_code == 429:
        return "429 Rate Limited"
    else:
        info = reg_page.json().get("properties")
        attendee = Attendee()
        attendee.ticket_id = info.get("Ticket ID").get("title")[0].get("plain_text")
        attendee.first_name = info.get("First Name").get("rich_text")[0].get("plain_text")
        attendee.last_name = info.get("Last Name").get("rich_text")[0].get("plain_text")
        attendee.email = info.get("Preferred Email").get("email")
        if not attendee.email:
            attendee.email = info.get("School Email").get("email")
        preferred_name = info.get("Preferred Name").get("rich_text", [])
        preferred_name = None if len(preferred_name) == 0 else preferred_name[0].get("plain_text")
        attendee.preferred_name = preferred_name

        send_email(attendee)
        return "Successfully Sent Email", 200

def create_and_send_ticket(full_form_data):
    try:

        questions = full_form_data["data"]["fields"]  # Create Questions

        # Create User
        attendee = Attendee()
        attendee.ticket_id = full_form_data["data"]["responseId"]
        attendee.first_name = questions[0]["value"]
        attendee.last_name = questions[1]["value"]
        attendee.preferred_name = questions[2]["value"]

        # Set preferred email as default if available
        if questions[4]["value"]:
            attendee.email = questions[3]["value"]
        else:
            attendee.email = questions[6]["value"]

        # Create Ticket
        send_to_discord(attendee)
        send_email(attendee)
        return "Successfully Created Ticket", 201

    except KeyboardInterrupt as k:
        print(k)
        print("Ending the Program")
        sys.exit(0)
    except Exception as e:
        print(e)
        traceback.print_exception(e)
        return "Something went Wrong", 503

def send_to_discord(attendee):
    url = env.get("DISCORD_WEBHOOK_URL")
    header = {
        "Accept": "application/json"
    }
    if attendee.ticket_id:
        body = {
            "content": f"{attendee.first_name} {attendee.last_name} has registered!\n"
                       f"Email: `{attendee.email}`\n"
                       f"Ticket Number: `{attendee.ticket_id}`\n"
                       f"Ticket Barcode: [link](https://devhacks2024.khathepham.com{url_for('qr_code', ticket_id=attendee.ticket_id)})"
        }
    else:
        body = {
            "content": f"WARNING: {attendee.first_name} {attendee.last_name} tried to register, "
                       f"but something went wrong.\nEmail: `{attendee.email}`"
        }
    r = requests.post(url, headers=header, data=body)
    print(f"{r.status_code} {r.reason}")


def send_email(attendee):
    s = smtplib.SMTP('smtp.gmail.com', 587)
    s.starttls()
    s.login(DEVCLUB_EMAIL, os.environ["GOOGLE_APP_PASS"])

    with open("static/styles/style.css", "r") as fil:
        css = fil.read()

    with open("templates/email.html", 'r') as f:
        text = f.read()
        template = jinja2.Template(text)
    content = template.render(attendee=attendee, css=css)

    message = MIMEMultipart()
    message.attach(MIMEText(content, 'html'))
    message["Subject"] = f".devHacks 2025 Ticket - {attendee.ticket_id}"
    message["From"] = DEVCLUB_EMAIL
    message["To"] = attendee.email

    qr = attendee.ticket_qr()
    b = io.BytesIO()
    qr.save(b, kind="png", scale=6)

    image = MIMEImage(b.getvalue(), Name=f"{attendee.ticket_id}.png", _subtype="png")
    image.add_header('Content-ID', attendee.ticket_id)
    message.attach(image)
    s.sendmail(DEVCLUB_EMAIL, attendee.email, message.as_string())


if __name__ == '__main__':
    app.run(debug=True, port=5001)
