import os, re, time, json, asyncio, random
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from telegram import Bot

# =======================
# VARIÁVEIS (Railway)
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVALO_SEG = int(os.getenv("INTERVALO_SEG", "300"))

if not BOT_TOKEN:
    raise RuntimeError("Faltou BOT_TOKEN")
if not CHAT_ID:
    raise RuntimeError("Faltou CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 RadarOfertasBot/3.0",
}

KEYWORDS = [
    "air fryer","fone bluetooth","smartwatch","robo aspirador","mop giratorio",
    "liquidificador","cafeteira","panela eletrica","lampada led","fita led",
    "caixa de som bluetooth","carregador turbo","power bank","ring light",
    "mouse gamer","teclado gamer","roteador wifi","camera wifi",
    "fralda bebe","lenço umedecido","mamadeira","secador cabelo",
    "barbeador eletrico","halter","corda pular","parafusadeira",
    "furadeira","kit ferramentas","lanterna led","suporte celular carro"
]

CACHE_FILE = "sent_cache.json"

def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"sent": {}}

def save_cache(data):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)

def extract_item_id(url):
    m = re.search(r"(MLB-?\d+)", url.upper())
    return m.group(1).replace("-", "") if m else None

async def fetch_listing(keyword):
    url = f"https://lista.mercadolivre.com.br/{quote_plus(keyword)}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.get(url)
        soup = BeautifulSoup(r.text, "lxml")

    items = []
    for card in soup.select("li.ui-search-layout__item")[:10]:
        title = card.select_one("h2.ui-search-item__title")
        link = card.select_one("a.ui-search-link")
        price = card.select_one("span.andes-money-amount__fraction")

        if not (title and link and price):
            continue

        items.append({
            "title": title.get_text(strip=True),
            "link": link.get("href"),
            "price": price.get_text(strip=True),
            "id": extract_item_id(link.get("href"))
        })
    return items

def make_msg(p):
    return (
        "🔥 OFERTA ENCONTRADA 🔥\n\n"
        f"📦 {p['title']}\n"
        f"💰 R$ {p['price']}\n\n"
        "🛒 Comprar:\n"
        "SEU_LINK_AFILIADO_AQUI\n\n"
        f"🔗 {p['link']}"
    )

async def main():
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot online — enviando ofertas automaticamente.")

    cache = load_cache()
    sent = cache.get("sent", {})

    while True:
        try:
            keyword = random.choice(KEYWORDS)
            items = await fetch_listing(keyword)

            for it in items:
                uid = it["id"] or it["link"]
                if uid in sent:
                    continue

                msg = make_msg(it)
                await bot.send_message(chat_id=CHAT_ID, text=msg)

                sent[uid] = time.time()
                cache["sent"] = sent
                save_cache(cache)
                break

            print("Ciclo ok")

        except Exception as e:
            print("ERRO:", e)

        await asyncio.sleep(INTERVALO_SEG)

if __name__ == "__main__":
    asyncio.run(main())
