# Деплой на VPS (Ubuntu/Debian): systemd + Caddy

Один код, по экземпляру службы `booking@<бизнес>` со своим `.env`, базой и портом.

```sh
# от root
apt update && apt install -y git curl postgresql redis-server caddy
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
# Node.js 24 для сборки мини-приложения → /opt/node (см. nodejs.org/dist/latest-v24.x)
useradd --create-home --shell /bin/bash booking
sudo -u postgres createuser booking
sudo -u postgres createdb -O booking barbershop
sudo -u postgres psql barbershop -c "CREATE EXTENSION IF NOT EXISTS btree_gist"   # нужен суперпользователь
sudo -u booking git clone https://github.com/egorstep147/telegram-booking-bot.git /home/booking/telegram-booking-bot
sudo -u booking mkdir -p /home/booking/envs
```

`/home/booking/envs/barbershop.env` (права 600, комментарии — только отдельной строкой):
```
BOT_TOKEN=...
NICHE=barbershop
DATABASE_URL=postgresql:///barbershop?host=/var/run/postgresql
REDIS_URL=redis://localhost:6379/2
PORT=8085
ADMIN_IDS=...
WEBAPP_URL=https://book.130-17-30-251.sslip.io:8443/
WEBHOOK_URL=https://book.130-17-30-251.sslip.io:8443
WEBHOOK_SECRET=...
PAYMENT_TOKEN=...
```

```sh
cp deploy/booking@.service /etc/systemd/system/ && systemctl daemon-reload
sh deploy/update.sh                                   # зависимости и сборка мини-приложения
sudo -u booking sh -c 'cd ~/telegram-booking-bot && set -a && . ~/envs/barbershop.env && set +a && .venv/bin/booking migrate && .venv/bin/booking seed'
systemctl enable --now booking@barbershop
```

Caddy (`/etc/caddy/Caddyfile`, порт 8443 — если 443 занят; вебхуки Telegram принимают 443/80/88/8443):
```
book.130-17-30-251.sslip.io:8443 {
	reverse_proxy 127.0.0.1:8085
}
```

Обновление: `sh /home/booking/telegram-booking-bot/deploy/update.sh`.
Бэкап: `0 4 * * * pg_dump barbershop > /home/booking/backup-$(date +\%a).sql` в crontab пользователя booking.
