#!/bin/bash

exec gunicorn --config gunicorn_config.py checkin_service:app --capture-output --enable-stdio-inheritance