import os, re, time, json, asyncio, random
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO_SEG = int(os.getenv("INTERVALO_SEG", "300"))
TERMS_PER_CYCLE = int(os.getenv("TERMS_PER_CYCLE", "6"))
RESULTS_TO_SCAN = int(os.getenv("RESULTS_TO_SCAN", "12"))
MAX_SEND_PER_CYCLE = int(os.getenv("MAX_SEND_PER_CYCLE", "1"))
INTERNAL_DELAY_SEC = float(os.getenv("INTERNAL_DELAY_SEC", "0.8"))

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "pt-BR,pt;q=0.9"
}

KEYWORDS = [
    "air fryer","liquidificador","cafeteira","panela eletrica","kit cozinha",
    "mop giratorio","aspirador","organizador","lampada led","fita led",
    "fone bluetooth","caixa bluetooth","smartwatch","carregador turbo","power bank",
    "mouse gamer","teclado gamer","headset gamer",
    "fralda bebe","lenço umedecido",
    "secador cabelo","chapinha","barbeador",
    "halter","tapete yoga",
    "parafusadeira","furadeira",
    "suporte celular carro"
]

CACHE_FILE = "sent_cache.json"

def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"sent": {}}

def save_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except:
        pass

def extract_item_id(url):
    m = re.search(r"(MLB-?\d+)", url.upper())
    return m.group(1).replace("-", "") if m else None

async def fetch_listing(keyword):
    url = f"https://lista.mercadolivre.com.br/{quote_plus(keyword)}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.get(url)
    soup = BeautifulSoup(r.text, "lxml")
    cards = soup.select("li.ui-search-layout__item")[:RESULTS_TO_SCAN]

    items = []
    for c in cards:
        t = c.select_one("h2")
        a = c.select_one("a.ui-search-link")
        p = c.select_one("span.andes-money-amount__fraction")
        if not (t and a and p): continue
        txt = c.get_text(" ", strip=True).lower()
        items.append({
            "title": t.get_text(strip=True),
            "link": a.get("href"),
            "price": p.get_text(strip=True),
            "coupon": "cupom" in txt,
            "frete": "frete grátis" in txt,
            "id": extract_item_id(a.get("href"))
        })
    return items

def make_msg(p):
    cupom = "\n🎟️ POSSÍVEL CUPOM NO ANÚNCIO" if p["coupon"] else ""
    frete = "\n🚚 POSSÍVEL FRETE GRÁTIS" if p["frete"] else ""
    return f"""🔥 OFERTA ENCONTRADA 🔥

📦 {p['title']}
💰 R$ {p['price']}{cupom}{frete}

🛒 Coloque seu link de afiliado aqui
🔗 {p['link']}

⚡ Estoque pode acabar!
"""

async def main():
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot online — enviando ofertas automaticamente.")

    cache = load_cache()
    sent = cache["sent"]

    while True:
        try:
            sent_cycle = 0
            for kw in random.sample(KEYWORDS, k=min(TERMS_PER_CYCLE, len(KEYWORDS))):
                if sent_cycle >= MAX_SEND_PER_CYCLE:
                    break

                items = await fetch_listing(kw)
                for it in items:
                    uid = it["id"] or it["link"]
                    if uid in sent:
                        continue

                    await bot.send_message(chat_id=CHAT_ID, text=make_msg(it))
                    sent[uid] = time.time()
                    save_cache(cache)
                    sent_cycle += 1
                    break

                await asyncio.sleep(INTERNAL_DELAY_SEC)

            print(f"Ciclo ok | enviadas: {sent_cycle}")
        except Exception as e:
            print("Erro:", e)

        await asyncio.sleep(INTERVALO_SEG)

if __name__ == "__main__":
    asyncio.run(main())
