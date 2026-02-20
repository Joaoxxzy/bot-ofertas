import os
import asyncio
import random
import time
import json
import re
import httpx
from bs4 import BeautifulSoup
from telegram import Bot
from urllib.parse import quote_plus

# ======================
# VARIÁVEIS DO RAILWAY
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVALO_SEG = int(os.getenv("INTERVALO_SEG", "120"))
MAX_SEND_PER_CYCLE = int(os.getenv("MAX_SEND_PER_CYCLE", "1"))
TERMS_PER_CYCLE = int(os.getenv("TERMS_PER_CYCLE", "4"))
RESULTS_TO_SCAN = int(os.getenv("RESULTS_TO_SCAN", "8"))

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("Faltou BOT_TOKEN ou CHAT_ID nas Variables")

# ======================
# HEADERS
# ======================
HEADERS = {
    "User-Agent": "Mozilla/5.0 RadarOfertasBot/3.0",
    "Accept-Language": "pt-BR,pt;q=0.9"
}

# ======================
# KEYWORDS GRANDES
# ======================
KEYWORDS = [
    "air fryer","liquidificador","cafeteira","panela eletrica","jogo de panelas",
    "mop giratorio","aspirador vertical","robo aspirador","caixa organizadora",
    "lampada led","fita led","extensao eletrica",
    "fone bluetooth","caixa de som bluetooth","smartwatch","carregador turbo",
    "power bank","suporte celular","roteador wifi",
    "headset gamer","mouse gamer","teclado gamer",
    "fralda bebe","lenço umedecido","mamadeira",
    "secador cabelo","chapinha","barbeador eletrico",
    "halter","corda pular","tapete yoga",
    "parafusadeira","furadeira","lanterna led",
    "suporte celular carro","carregador veicular"
]

CACHE_FILE = "sent_cache.json"

# ======================
# CACHE
# ======================
def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"sent": {}}

def save_cache(data):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)

# ======================
# EXTRAIR ID
# ======================
def extract_item_id(url):
    m = re.search(r"(MLB-?\d+)", url.upper())
    return m.group(1).replace("-", "") if m else None

# ======================
# BUSCAR LISTAGEM
# ======================
async def fetch_listing(keyword):
    url = f"https://lista.mercadolivre.com.br/{quote_plus(keyword)}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.get(url)
        soup = BeautifulSoup(r.text, "lxml")

    items = []
    cards = soup.select("li.ui-search-layout__item")[:RESULTS_TO_SCAN]

    for c in cards:
        try:
            title = c.select_one("h2").get_text(strip=True)
            link = c.select_one("a.ui-search-link")["href"]
            price = c.select_one("span.andes-money-amount__fraction").get_text(strip=True)
            txt = c.get_text(" ").lower()

            items.append({
                "title": title,
                "link": link,
                "price": price,
                "coupon": "cupom" in txt,
                "frete": "frete grátis" in txt
            })
        except:
            continue

    return items

# ======================
# ESCOLHER PRODUTO
# ======================
async def pick_product(sent_cache):
    keywords = random.sample(KEYWORDS, TERMS_PER_CYCLE)

    for kw in keywords:
        items = await fetch_listing(kw)

        for it in items:
            uid = extract_item_id(it["link"]) or it["link"]
            if uid in sent_cache:
                continue
            it["keyword"] = kw
            it["uid"] = uid
            return it

    return None

# ======================
# MONTAR MENSAGEM
# ======================
def build_message(p):
    cupom = "\n🎟️ *POSSÍVEL CUPOM DISPONÍVEL*" if p["coupon"] else ""
    frete = "\n🚚 *Possível frete grátis*" if p["frete"] else ""

    return (
        "🔥 *OFERTA ENCONTRADA* 🔥\n\n"
        f"📦 {p['title']}\n"
        f"💰 R$ {p['price']}\n"
        f"{cupom}{frete}\n\n"
        "🛒 *Comprar agora:*\n"
        "SEU_LINK_AFILIADO_AQUI\n\n"
        f"📂 Categoria: {p['keyword']}\n"
        f"🔗 {p['link']}"
    )

# ======================
# LOOP PRINCIPAL
# ======================
async def main():
    bot = Bot(BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="🚀 Bot iniciado e rodando 24h!")

    cache = load_cache()
    sent = cache["sent"]

    while True:
        try:
            sent_now = 0

            for _ in range(MAX_SEND_PER_CYCLE):
                product = await pick_product(sent)

                if product:
                    msg = build_message(product)
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
                    sent[product["uid"]] = time.time()
                    save_cache(cache)
                    sent_now += 1

            print(f"Ciclo ok | enviadas: {sent_now}")

        except Exception as e:
            print("ERRO:", e)

        await asyncio.sleep(INTERVALO_SEG)

# ======================
# START
# ======================
if __name__ == "__main__":
    asyncio.run(main())
