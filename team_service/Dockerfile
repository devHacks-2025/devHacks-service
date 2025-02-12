FROM python:3.11.11-bookworm

WORKDIR /devHacks-registration-service

COPY requirements.txt requirements.txt
RUN pip3 install --upgrade pip
RUN pip3 install -r requirements.txt

COPY . .

EXPOSE 9459

RUN chmod +x ./gunicorn-start.sh
ENTRYPOINT ["sh"]
CMD ["gunicorn-start.sh"]