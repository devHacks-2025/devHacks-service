import logging
import smtplib
import sys
import time
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
from notion_client import Client, APIResponseError, APIErrorCode

DEVCLUB_EMAIL = "umdevclub@gmail.com"

app = Flask(__name__)
CORS(app)
notion = Client(auth=os.environ["NOTION_KEY"], log_level=logging.DEBUG)
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

@app.route('/')
def hello_world():
    return 'Hello World!'

@app.route('/api/v25/register', methods=["POST"])
def register():
    full_form_data = request.get_json()  # Webhook Data
    r = create_and_send_ticket(full_form_data)
    logging.debug(r)
    return r

@app.route('/api/v25/tickets/<ticket_id>', methods=["GET"])
def get_qr_code(ticket_id: str):
    qr = segno.make_qr(ticket_id)
    b = io.BytesIO()
    qr.save(b, kind="png", scale=10)
    return Response(b.getvalue(), mimetype='image/png')

# Registrants are stored as pages in a Notion database
@app.route('/api/v25/tickets/<notion_page_id>', methods=["POST"])
def resend_qr_code(notion_page_id: str):
    logging.info(f"Received request for page: {notion_page_id}")

    try:
        reg_page = notion.pages.retrieve(notion_page_id)
        logging.info(f"Retrieved Page: {reg_page}\n")

        info = reg_page.get("properties")
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
        confirm_qr(reg_page.get('id'))
        return "Successfully Sent Email", 200
    except APIResponseError as error:
        if error.code == APIErrorCode.ObjectNotFound:
            return "404 ID Not Found", 404
        elif APIErrorCode.InvalidRequest == 400 or APIErrorCode.RateLimited == 429:
            return "429 Rate Limited", 429
        else:
            return "Sorry, something happened on our side.", 500

@app.route('/api/v25/tickets/resend-all', methods=["POST"])
def resend_all():
    try:
        database_id = os.environ["NOTION_DATABASE_ID"]
        count = 0
        next_page = None  

        while True:  # Loop until there are no more pages
            database_parameters = {"database_id": database_id}
            if next_page:
                database_parameters["start_cursor"] = next_page

            response = notion.databases.query(**database_parameters)  
            results = response.get("results", [])

            for page in results:
                page_id = page.get("id")
                qr_sent = page.get("properties").get("QR Sent", {}).get("checkbox", False)

                
                if  not qr_sent:
                    logging.info(f"Would resend QR code for page: {page_id}")
                    count += 1  
                    resend_qr_code(page_id)
                    confirm_qr(page_id)
                    time.sleep(0.5)  

            next_page = response.get("next_cursor")  
            if not next_page:  
                break

        logging.info(f"Total attendees processed: {count}")
        return f"Test completed. {count} attendees processed.", 200

    except Exception as e:
        logging.error(f"Error in resending QR codes: {str(e)}")
        return "Internal Server Error", 500

def get_total_registered_count():
    database_id = os.environ["NOTION_DATABASE_ID"]
    total_count = 0
    next_cursor = None

    while True:
        database_parameters = {"database_id": database_id}
        if next_cursor:
            database_parameters["start_cursor"] = next_cursor

        response = notion.databases.query(**database_parameters)
        results = response.get("results", [])

        # Count each individual registrant
        for page in results:
            total_count += 1

        next_cursor = response.get("next_cursor")
        if not next_cursor:
            break

    return total_count


def confirm_qr(page_id):
    notion.pages.update(page_id, properties={ 'QR Sent': { 'checkbox': True }})

def create_and_send_ticket(full_form_data):
    try:

        questions = full_form_data["data"]["fields"]  # Create Questions

        # Create User
        attendee = Attendee()
        attendee.ticket_id = full_form_data["data"]["responseId"]
        attendee.first_name = questions[0]["value"]
        attendee.last_name = questions[1]["value"]

        for question in questions:
            if question["key"] == "question_QMxv0X" and question.get("value"):
                attendee.preferred_name = question.get("value")
            if question["key"] == "question_AzGkvo":
                attendee.email = question.get("value")
            if question["key"] == "question_AK6Aly" and question.get("value"):
                attendee.email = question.get("value")

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
    url = os.environ["DISCORD_WEBHOOK_URL"]
    header = {
        "Accept": "application/json"
    }
    total_registered= get_total_registered_count()
    if attendee.ticket_id:
        body = {
            "content": f"{attendee.first_name} {attendee.last_name} has registered!\n"
                       f"Email: `{attendee.email}`\n"
                       f"Ticket Number: `{attendee.ticket_id}`\n"
                       f"Ticket Barcode: [link](https://devhacksapi.khathepham.com{url_for('get_qr_code', ticket_id=attendee.ticket_id)})\n"
                       f"Total Registrations: `{total_registered}`"
        }
    else:
        body = {
            "content": f"WARNING: {attendee.first_name} {attendee.last_name} tried to register, "
                       f"but something went wrong.\nEmail: `{attendee.email}`"
        }
    r = requests.post(url, headers=header, data=body)
    logging.info(f"{r.status_code} {r.reason}")


def send_email(attendee):
    s = smtplib.SMTP('smtp.gmail.com', 587)
    s.starttls()
    s.login(DEVCLUB_EMAIL, os.environ["GOOGLE_APP_PASS"])

    with open("static/templates/email.html", 'r') as f:
        text = f.read()
        template = jinja2.Template(text)
    content = template.render(attendee=attendee)

    message = MIMEMultipart()
    message.attach(MIMEText(content, 'html'))
    message["Subject"] = f".devHacks 2025 Ticket - {attendee.ticket_id}"
    message["From"] = DEVCLUB_EMAIL
    message["To"] = attendee.email

    qr = attendee.ticket_qr()
    b = io.BytesIO()
    qr.save(b, kind="png", scale=10)

    image = MIMEImage(b.getvalue(), Name=f"{attendee.ticket_id}.png", _subtype="png")
    image.add_header('Content-ID', attendee.ticket_id)
    message.attach(image)
    s.sendmail(DEVCLUB_EMAIL, attendee.email, message.as_string())


if __name__ == '__main__':
    app.run(debug=True, port=5001)
