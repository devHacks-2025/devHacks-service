#!/bin/bash

exec gunicorn --config gunicorn_config.py checkin_service:app