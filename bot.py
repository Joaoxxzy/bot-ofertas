import os, re, time, json, asyncio, random
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Intervalo entre ciclos (segundos). 300 = 5 min
INTERVALO_SEG = int(os.getenv("INTERVALO_SEG", "300"))

# Quantas mensagens mandar por ciclo (1 a 3 recomendado)
MAX_SEND_PER_CYCLE = int(os.getenv("MAX_SEND_PER_CYCLE", "2"))

# Quantos termos testar por ciclo
TERMS_PER_CYCLE = int(os.getenv("TERMS_PER_CYCLE", "6"))

# Quantos itens analisar em cada termo
RESULTS_TO_SCAN = int(os.getenv("RESULTS_TO_SCAN", "12"))

# Se não achar "oferta boa", manda "achadinho" mesmo assim
ALWAYS_SEND_FALLBACK = os.getenv("ALWAYS_SEND_FALLBACK", "1") == "1"

if not BOT_TOKEN:
    raise RuntimeError("Faltou BOT_TOKEN.")
if not CHAT_ID:
    raise RuntimeError("Faltou CHAT_ID.")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RadarOfertasBot/3.2",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

KEYWORDS = [
    # CASA / COZINHA
    "air fryer", "liquidificador", "batedeira", "cafeteira", "sanduicheira",
    "panela eletrica", "jogo de panelas", "kit utensilios cozinha",
    "potes hermeticos", "organizador cozinha",
    # LIMPEZA / ORGANIZAÇÃO
    "mop giratorio", "aspirador vertical", "robo aspirador",
    "caixa organizadora", "organizador armario", "sapateira",
    # ELÉTRICA / ILUMINAÇÃO
    "lampada led", "fita led", "filtro de linha", "extensão elétrica",
    # TECH
    "fone bluetooth", "caixa de som bluetooth", "smartwatch",
    "carregador turbo", "cabo usb tipo c", "power bank", "suporte celular",
    "roteador wifi", "camera segurança wifi",
    # GAMES/PC
    "mouse gamer", "teclado gamer", "headset gamer",
    # BEBÊ
    "fralda bebe", "lenço umedecido", "mamadeira",
    # BELEZA
    "secador de cabelo", "chapinha", "barbeador eletrico",
    # FERRAMENTAS
    "parafusadeira", "furadeira", "kit ferramentas",
    # AUTOMOTIVO
    "suporte celular carro", "carregador veicular",
]

CACHE_FILE = "sent_cache.json"

def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"sent": {}}

def save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

def prune_sent(sent: dict, days=7):
    now = time.time()
    limit = days * 24 * 3600
    return {k: v for k, v in sent.items() if now - v <= limit}

def extract_item_id(url: str):
    if not url:
        return None
    m = re.search(r"(MLB-?\d{6,})", url.upper())
    if not m:
        return None
    return m.group(1).replace("-", "")

def price_to_float(price_txt: str):
    t = (price_txt or "").replace(".", "").replace(",", ".")
    try:
        return float(t)
    except:
        return 0.0

# =============== BUSCA NO SITE (pode vir sem cards em alguns casos) ===============
async def fetch_listing(keyword: str, limit: int):
    url = f"https://lista.mercadolivre.com.br/{quote_plus(keyword)}"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=35) as client:
        r = await client.get(url)
        r.raise_for_status()
        html = r.text

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("li.ui-search-layout__item")[:limit]

    out = []
    for c in cards:
        title_el = c.select_one("h2.ui-search-item__title")
        link_el = c.select_one("a.ui-search-link")
        price_el = c.select_one("span.andes-money-amount__fraction")
        if not (title_el and link_el and price_el):
            continue

        title = title_el.get_text(strip=True)
        link = link_el.get("href", "")
        price_txt = price_el.get_text(strip=True)

        txt = c.get_text(" ", strip=True).lower()
        coupon_hint = any(p in txt for p in ["cupom", "com cupom", "aplicar cupom", "cupón"])
        free_ship_hint = ("frete grátis" in txt) or ("frete gratis" in txt)

        item_id = extract_item_id(link)

        out.append({
            "title": title,
            "link": link,
            "price_txt": price_txt,
            "coupon_hint": coupon_hint,
            "free_ship_hint": free_ship_hint,
            "item_id": item_id,
            "keyword": keyword
        })
    return out

# =============== ESCOLHA ===============
async def pick_offer_or_fallback(keyword: str, sent: dict):
    items = await fetch_listing(keyword, limit=RESULTS_TO_SCAN)
    if not items:
        return None

    # remove repetidos
    candidates = []
    for it in items:
        unique = it["item_id"] or it["link"]
        if unique in sent:
            continue
        candidates.append(it)

    if not candidates:
        return None

    # 1) tenta achar oferta “melhor”
    scored = []
    for it in candidates[:RESULTS_TO_SCAN]:
        price_val = price_to_float(it["price_txt"])
        score = 0
        score += 8 if it["coupon_hint"] else 0
        score += 6 if it["free_ship_hint"] else 0
        score += 2000 / max(price_val, 50)  # mais barato = mais score
        scored.append((score, it, price_val))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_it, best_price = scored[0]

    # define etiqueta
    etiqueta = "🔥 OFERTA" if (best_it["coupon_hint"] or best_it["free_ship_hint"] or best_score >= 35) else "✅ ACHADINHO"

    # se NÃO for oferta e você quiser sempre mandar, manda mesmo assim
    if etiqueta != "🔥 OFERTA" and not ALWAYS_SEND_FALLBACK:
        return None

    price_str = f"{best_price:.2f}".replace(".", ",") if best_price else best_it["price_txt"]

    return {
        "title": best_it["title"],
        "price": price_str,
        "link": best_it["link"],
        "coupon_hint": best_it["coupon_hint"],
        "free_ship_hint": best_it["free_ship_hint"],
        "keyword": best_it["keyword"],
        "unique": best_it["item_id"] or best_it["link"],
        "tag": etiqueta
    }

def make_message(p):
    cupom = ""
    if p.get("coupon_hint"):
        cupom = "*🎟️ Possível CUPOM no anúncio (verifique ao finalizar)*\n"
    frete = ""
    if p.get("free_ship_hint"):
        frete = "*🚚 Possível FRETE GRÁTIS no anúncio*\n"

    return (
        f"{p['tag']} NO MERCADO LIVRE\n\n"
        f"📦 {p['title']}\n"
        f"💰 R$ {p['price']}\n\n"
        f"{cupom}{frete}\n"
        "🛒 Comprar:\n"
        "SEU_LINK_AFILIADO_AQUI\n\n"
        "⚡ Pode acabar / estoque limitado!\n"
        f"📍 ({p['keyword']})\n"
        f"🔗 Link: {p['link']}"
    )

async def main():
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot online — vou mandar OFERTAS e também ACHADINHOS para não ficar sem post.")

    cache = load_cache()
    sent = prune_sent(cache.get("sent", {}), days=7)
    cache["sent"] = sent
    save_cache(cache)

    while True:
        try:
            sent_this_cycle = 0
            kws = random.sample(KEYWORDS, k=min(TERMS_PER_CYCLE, len(KEYWORDS)))

            for kw in kws:
                if sent_this_cycle >= MAX_SEND_PER_CYCLE:
                    break

                item = await pick_offer_or_fallback(kw, sent)
                if item:
                    msg = make_message(item)
                    await bot.send_message(chat_id=CHAT_ID, text=msg)
                    sent[item["unique"]] = time.time()
                    cache["sent"] = sent
                    save_cache(cache)
                    sent_this_cycle += 1

            print(f"Ciclo ok | enviadas: {sent_this_cycle} | próximo em {INTERVALO_SEG}s")

        except Exception as e:
            print("ERRO:", repr(e))

        await asyncio.sleep(INTERVALO_SEG)

if __name__ == "__main__":
    asyncio.run(main())
