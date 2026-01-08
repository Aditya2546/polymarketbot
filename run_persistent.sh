#!/bin/bash
cd /Users/adityamandal/polymarketbot
source venv/bin/activate

LOG_FILE="logs/master_persistent_$(date +%Y%m%d_%H%M%S).log"

echo "Starting persistent bot..." | tee -a $LOG_FILE
echo "Log file: $LOG_FILE"

while true; do
    echo "$(date): Starting bot..." | tee -a $LOG_FILE
    python run_all_bots.py 2>&1 | tee -a $LOG_FILE
    echo "$(date): Bot exited, restarting in 5s..." | tee -a $LOG_FILE
    sleep 5
done
