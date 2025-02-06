#!/bin/bash

exec gunicorn --config ./gunicorn_config.py registration_service:app