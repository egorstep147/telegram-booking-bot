#!/bin/sh
# Обновление (от root): sh /home/booking/telegram-booking-bot/deploy/update.sh
set -e
cd /home/booking/telegram-booking-bot
sudo -u booking git pull
sudo -u booking /usr/local/bin/uv sync --frozen --no-dev
sudo -u booking sh -c 'cd webapp && PATH=/opt/node/bin:$PATH npm ci --no-audit --no-fund && PATH=/opt/node/bin:$PATH npm run build'
systemctl restart 'booking@*'   # миграции — в ExecStartPre
systemctl --no-pager --lines=0 status 'booking@*'
