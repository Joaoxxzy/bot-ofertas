import os, time, random, asyncio, json, traceback
import httpx
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALO_SEG = int(os.getenv("INTERVALO_SEG", "300"))

KEYWORDS = [
    "air fryer","liquidificador","cafeteira","panela eletrica",
    "mop giratorio","aspirador","organizador",
    "lampada led","fone bluetooth","caixa bluetooth",
    "smartwatch","carregador turbo","power bank",
    "mouse gamer","teclado gamer",
    "fralda bebe","lenço umedecido",
    "secador cabelo","chapinha",
    "parafusadeira","furadeira",
    "suporte celular carro"
]

CACHE_FILE = "sent.json"

def load_cache():
    try:
        with open(CACHE_FILE,"r") as f:
            return json.load(f)
    except:
        return {"sent":{}}

def save_cache(data):
    try:
        with open(CACHE_FILE,"w") as f:
            json.dump(data,f)
    except:
        pass


async def buscar_oferta():
    kw = random.choice(KEYWORDS)
    url = f"https://api.mercadolibre.com/sites/MLB/search?q={kw}&sort=price_asc&limit=20"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        data = r.json()

    if not data.get("results"):
        return None

    prod = random.choice(data["results"])

    titulo = prod.get("title")
    preco = prod.get("price")
    link = prod.get("permalink")
    seller = prod.get("seller", {}).get("nickname","Vendedor")

    msg = f"""
🔥 OFERTA ENCONTRADA 🔥

📦 {titulo}
💰 R$ {preco}
🛡️ {seller}

🛒 Coloque seu link de afiliado aqui
🔗 {link}

⚡ Estoque pode acabar!
"""
    return msg, link


async def loop_principal(bot):
    cache = load_cache()
    sent = cache["sent"]

    while True:
        try:
            oferta = await buscar_oferta()

            if oferta:
                msg, link = oferta

                if link not in sent:
                    await bot.send_message(chat_id=CHAT_ID, text=msg)
                    sent[link] = time.time()
                    save_cache(cache)
                    print("Oferta enviada")
                else:
                    print("Repetida ignorada")

        except Exception:
            print("ERRO:")
            traceback.print_exc()

        await asyncio.sleep(INTERVALO_SEG)


async def main():
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot online — sistema estável ativo.")

    while True:
        try:
            await loop_principal(bot)
        except Exception:
            print("Loop reiniciado após erro")
            traceback.print_exc()
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
