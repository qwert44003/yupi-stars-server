YUPI STARS — СЕРВЕР ОПЛАТЫ TELEGRAM STARS
=========================================

ВАЖНО
-----
1) GitHub Pages не запускает Python. Этот сервер размещается отдельно на Render.
2) В render.yaml указан платный Render Starter + постоянный диск, потому что SQLite на бесплатном
   временном диске может потерять баланс и историю оплат после перезапуска/деплоя.
3) Не публикуйте BOT_TOKEN и WEBHOOK_SECRET в GitHub.
4) Сначала проверьте всё на тестовом боте/в тестовой среде Telegram. Не используйте реальные
   платежи до полной проверки.

ЧТО ДЕЛАЕТ СЕРВЕР
-----------------
- Принимает запрос Mini App на /create-invoice.
- Проверяет подпись Telegram.WebApp.initData.
- Создаёт invoice link в валюте XTR.
- Принимает Telegram webhook.
- Подтверждает pre_checkout_query.
- Начисляет игровые звёзды только после successful_payment.
- Защищает от повторного начисления по telegram_payment_charge_id.

ЗАПУСК НА RENDER
----------------
1. Создайте отдельный GitHub-репозиторий, например yupi-stars-server.
2. Загрузите в корень репозитория main.py, requirements.txt и render.yaml.
3. Откройте https://render.com/ и войдите через GitHub.
4. Нажмите New -> Blueprint и выберите репозиторий yupi-stars-server.
5. Render прочитает render.yaml. Для постоянного SQLite-хранилища нужен план Starter
   с persistent disk (платный). Не удаляйте диск после запуска.
6. В Environment добавьте:
   BOT_TOKEN = токен вашего бота от @BotFather
   WEBHOOK_SECRET = случайная длинная строка из букв и цифр (1-64 символа)
   SUPPORT_USERNAME = ваш username поддержки, например @yourname
   WEB_APP_URL = https://qwert44003.github.io/yupistars-/
7. Дождитесь статуса Live. Скопируйте адрес сервиса, например:
   https://yupi-stars-payments.onrender.com

НАСТРОЙКА TELEGRAM WEBHOOK
--------------------------
Замените значения и откройте ссылку в браузере (не отправляйте её никому:
в ней находится токен бота):

https://api.telegram.org/botВАШ_BOT_TOKEN/setWebhook?url=https://ВАШ-СЕРВЕР.onrender.com/telegram-webhook&secret_token=ВАШ_WEBHOOK_SECRET&allowed_updates=%5B%22message%22%2C%22pre_checkout_query%22%5D

Проверьте webhook:
https://api.telegram.org/botВАШ_BOT_TOKEN/getWebhookInfo

ПОДКЛЮЧЕНИЕ К MINI APP
---------------------
В HTML Mini App в месте, где пользователь нажимает кнопку пополнения, используйте такой код.
Замените SERVER_URL на адрес вашего Render-сервера:

async function buyStars(amount) {
  const tg = window.Telegram.WebApp;
  const response = await fetch("https://SERVER_URL.onrender.com/create-invoice", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": tg.initData
    },
    body: JSON.stringify({ amount: Number(amount) })
  });

  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Не удалось создать счёт");

  tg.openInvoice(data.invoice_link, (status) => {
    if (status === "paid") {
      // Обновите баланс запросом GET /balance, а не начисляйте его здесь.
      console.log("Платёж прошёл; баланс проверяется сервером.");
    }
  });
}

async function refreshBalance() {
  const tg = window.Telegram.WebApp;
  const response = await fetch("https://SERVER_URL.onrender.com/balance", {
    headers: { "X-Telegram-Init-Data": tg.initData }
  });
  if (!response.ok) throw new Error("Не удалось получить баланс");
  const data = await response.json();
  return data.balance;
}

ВАЖНО: Вызов buyStars(100) означает оплату 100 Telegram Stars и начисление 100 игровых звёзд.
Кнопка Mini App не должна сама менять баланс. Баланс нужно читать с GET /balance.

ПЕРЕД РЕАЛЬНЫМ ЗАПУСКОМ
----------------------
- Проверьте, что бот открывается в Telegram и Mini App получает непустой initData.
- Проверьте /health: должен вернуть {"ok": true}.
- Сделайте тестовый платёж и убедитесь, что баланс вырос ровно на сумму оплаты.
- Проверьте повторную доставку webhook: повторного начисления быть не должно.
- Настройте резервные копии постоянного диска/базы данных.
- Заполните реальные правила /terms и реальный контакт /paysupport.
- Telegram требует для цифровых товаров оплату внутри Telegram исключительно в Stars (XTR).
- Telegram требует обработку pre_checkout_query и выдачу цифрового товара только после successful_payment.

ДОКУМЕНТАЦИЯ
------------
https://core.telegram.org/bots/payments-stars
https://core.telegram.org/bots/api
