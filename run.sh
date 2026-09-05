#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
export $(grep -v '^#' .env | xargs)
python bot.py
