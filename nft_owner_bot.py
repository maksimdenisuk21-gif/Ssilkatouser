# Работает и на телефоне (Pydroid 3), и на Render.
# Локально спросит данные в консоли, на Render возьмёт из переменных окружения.
import json
import os
import re

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

CONFIG_FILE = "nft_config.json"


def load_config():
    # 1) Переменные окружения (Render)
    env = (os.getenv("API_ID"), os.getenv("API_HASH"), os.getenv("BOT_TOKEN"))
    if all(env):
        return {"api_id": int(env[0]), "api_hash": env[1], "bot_token": env[2]}

    # 2) Сохранённый файл (телефон)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            if all(cfg.get(k) for k in ("api_id", "api_hash", "bot_token")):
                print("Найдены сохранённые данные.")
                if input("Использовать их? (Enter = да, n = ввести заново): ").strip().lower() != "n":
                    return cfg
        except Exception:
            pass

    # 3) Ввод в консоли
    print("=== Настройка бота ===")
    while True:
        api_id = input("Введите API ID (число): ").strip()
        if api_id.isdigit():
            break
        print("API ID должен быть числом, попробуйте ещё раз.")
    while True:
        api_hash = input("Введите API HASH (32 символа): ").strip()
        if len(api_hash) == 32:
            break
        print("API HASH должен быть длиной 32 символа, попробуйте ещё раз.")
    while True:
        bot_token = input("Введите BOT TOKEN (от @BotFather): ").strip()
        if re.fullmatch(r"\d+:[A-Za-z0-9_\-]+", bot_token):
            break
        print("Токен выглядит как 123456:ABC-DEF..., попробуйте ещё раз.")

    cfg = {"api_id": int(api_id), "api_hash": api_hash, "bot_token": bot_token}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    print("Данные сохранены, в следующий раз вводить не придётся.\n")
    return cfg


cfg = load_config()
# Сессия в памяти: не нужны файлы, подходит для Render
client = TelegramClient(StringSession(), cfg["api_id"], cfg["api_hash"])

NFT_RE = re.compile(r"t\.me/nft/([A-Za-z0-9_\-]+)")
OWNER_RE = re.compile(
    r"Owner</th>\s*<td>\s*(?:<a[^>]+href=\"https://t\.me/([A-Za-z0-9_]+)\"[^>]*>(.*?)</a>|(.*?))\s*</td>",
    re.S | re.I,
)


def clean(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


async def fetch_owner(slug):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"https://t.me/nft/{slug}") as r:
            if r.status != 200:
                return None
            html = await r.text()
    m = OWNER_RE.search(html)
    if not m:
        return None
    username, name_linked, name_plain = m.groups()
    return username, clean(name_linked or name_plain)


@client.on(events.NewMessage(pattern=r"(?s).*t\.me/nft/[A-Za-z0-9_\-]+.*"))
async def handler(event):
    slug = NFT_RE.search(event.raw_text).group(1)
    print("Запрос:", slug)
    try:
        owner = await fetch_owner(slug)
    except Exception as e:
        print("Ошибка загрузки страницы:", e)
        return await event.reply("Ошибка при загрузке страницы NFT.")
    if not owner:
        return await event.reply("Не удалось найти владельца (или NFT не существует).")
    username, name = owner
    if not username:
        return await event.reply(
            f"Владелец: {name}\nЮзернейм скрыт или отсутствует, ID получить нельзя."
        )
    try:
        user = await client.get_entity(username)
        uid = user.id
    except Exception as e:
        print("Ошибка получения ID:", e)
        uid = "не удалось получить"
    await event.reply(
        f"Владелец: {name}\n"
        f"Юзернейм: @{username}\n"
        f"ID: {uid}\n"
        f"Профиль: https://t.me/{username}\n"
        f"Ссылка по ID: tg://user?id={uid}",
        link_preview=False,
    )


@client.on(events.NewMessage(pattern="/start"))
async def start(event):
    await event.reply("Пришлите ссылку на NFT, например t.me/nft/PlushPepe-123")


async def start_web():
    # Render требует, чтобы сервис слушал порт. Заодно это адрес для пинга.
    port = os.getenv("PORT")
    if not port:
        return
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    print("Веб-сервер на порту", port)


async def main():
    await start_web()
    await client.start(bot_token=cfg["bot_token"])
    print("Бот запущен. Не закрывайте это окно.")
    await client.run_until_disconnected()


try:
    client.loop.run_until_complete(main())
except Exception as e:
    print("Не удалось запустить бота:", e)
    print("Проверьте данные. Локально удалите файл", CONFIG_FILE, "и запустите заново.")
