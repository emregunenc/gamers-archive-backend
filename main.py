from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import requests
import re
import unicodedata
import smtplib
import resend
import urllib.request
import json as _json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pydantic import BaseModel
import json
import os
from typing import Optional

app = FastAPI(title="Gamer's Archive API")

# PS Plus catalog cache
import time
_psplus_cache = {"games": [], "last_updated": 0}

def get_psplus_catalog():
    global _psplus_cache
    # Refresh every 24 hours
    if time.time() - _psplus_cache["last_updated"] < 86400 and _psplus_cache["games"]:
        return _psplus_cache["games"]
    try:
        games = []
        page = 0
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        while True:
            r = requests.get(
                f"https://store.playstation.com/en-tr/category/44d8bb20-653e-431e-8ad0-c0a365f68d2f/{page+1}",
                headers=headers, timeout=15
            )
            # Try alternative API
            r2 = requests.get(
                "https://web.np.playstation.com/api/graphql/v1/op",
                params={
                    "operationName": "categoryGridRetrieve",
                    "variables": json.dumps({"id": "44d8bb20-653e-431e-8ad0-c0a365f68d2f", "pageArgs": {"size": 100, "offset": page * 100}, "sortBy": {"name": "score", "isAscending": False}, "filterBy": [], "languageCode": "tr", "countryCode": "TR"}),
                    "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": "4c2afe20a8daf10a29e59e1e8c39e7bba3b0de91bc7d4cb4aa78cd51f22a2e0d"}})
                },
                headers={**headers, "Origin": "https://store.playstation.com"},
                timeout=15
            )
            if r2.status_code == 200:
                data = r2.json()
                products = data.get("data", {}).get("categoryGridRetrieve", {}).get("products", [])
                if not products:
                    break
                for p in products:
                    name = p.get("name", "")
                    if name:
                        games.append(name)
                if len(products) < 100:
                    break
                page += 1
            else:
                break
        if games:
            _psplus_cache = {"games": games, "last_updated": time.time()}
            return games
    except Exception as e:
        print(f"PS Plus catalog error: {e}")
    # Fallback to JSON file
    try:
        with open("psplus_games.json", "r", encoding="utf-8") as f:
            return json.load(f).get("games", [])
    except:
        return []

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- KONFİGÜRASYON ---
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "E722F690EA2642D98FA54A973F703860")
ITAD_API_KEY = os.getenv("ITAD_API_KEY", "fb00f3da8717cec28c29230c6751e795aaeec8d6")
RAWG_API_KEY = os.getenv("RAWG_API_KEY", "d0cc05e711884b91911e36cb2f2e44cc")
IGDB_CLIENT_ID = os.getenv("IGDB_CLIENT_ID", "2bugrxp3scbr1l493je0fgex1mop4h")
IGDB_CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET", "j400fdeqok9biwj8x879k980iuz8ue")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# --- SUPABASE ---
print(f"SUPABASE_URL: {SUPABASE_URL[:20] if SUPABASE_URL else 'EMPTY'}")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# --- MODELLER ---
class GameAdd(BaseModel):
    user_id: str
    name: str
    category_id: Optional[str] = None
    status: str = "backlog"

class GameUpdate(BaseModel):
    status: Optional[str] = None
    category_id: Optional[str] = None

class CategoryAdd(BaseModel):
    user_id: str
    name: str

# --- LOCALE CONFIG ---
LOCALE_CONFIG = {
    "tr":    {"cc": "TR", "lang": "turkish",  "currency": "TRY", "symbol": "TL", "itad_country": "TR", "ps_country": "TR", "ps_lang": "tr", "ps_locale": "tr-tr"},
    "de":    {"cc": "DE", "lang": "german",   "currency": "EUR", "symbol": "€",  "itad_country": "DE", "ps_country": "DE", "ps_lang": "de", "ps_locale": "de-de"},
    "es":    {"cc": "ES", "lang": "spanish",  "currency": "EUR", "symbol": "€",  "itad_country": "ES", "ps_country": "ES", "ps_lang": "es", "ps_locale": "es-es"},
    "fr":    {"cc": "FR", "lang": "french",   "currency": "EUR", "symbol": "€",  "itad_country": "FR", "ps_country": "FR", "ps_lang": "fr", "ps_locale": "fr-fr"},
    "ja":    {"cc": "JP", "lang": "japanese", "currency": "JPY", "symbol": "¥",  "itad_country": "JP", "ps_country": "JP", "ps_lang": "ja", "ps_locale": "ja-jp"},
    "en_uk": {"cc": "GB", "lang": "english",  "currency": "GBP", "symbol": "£",  "itad_country": "GB", "ps_country": "GB", "ps_lang": "en", "ps_locale": "en-gb"},
    "en":    {"cc": "US", "lang": "english",  "currency": "USD", "symbol": "$",  "itad_country": "US", "ps_country": "US", "ps_lang": "en", "ps_locale": "en-us"},
}

COUNTRY_TO_LANG = {
    "TR": "tr", "DE": "de", "AT": "de", "CH": "de",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es",
    "FR": "fr", "BE": "fr", "JP": "ja",
    "GB": "en_uk", "US": "en", "CA": "en", "AU": "en",
}

def get_locale_config(lang: str) -> dict:
    return LOCALE_CONFIG.get(lang, LOCALE_CONFIG["en"])

def format_price(amount: float, locale: dict, usd_amount: float = None) -> str:
    currency = locale["currency"]
    symbol = locale["symbol"]
    suffix = f" (${usd_amount:.2f})" if usd_amount and currency != "USD" else ""
    if currency == "USD":
        return f"${amount:.2f}"
    elif currency == "JPY":
        return f"{amount:.0f}{symbol}{suffix}"
    elif currency == "TRY":
        return f"{amount:.0f} {symbol}{suffix}"
    else:
        return f"{amount:.2f}{symbol}{suffix}"

# --- IGDB TOKEN ---
def get_igdb_token():
    try:
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": IGDB_CLIENT_ID,
                "client_secret": IGDB_CLIENT_SECRET,
                "grant_type": "client_credentials"
            },
            timeout=10
        )
        return r.json().get('access_token')
    except:
        return None

# --- GENEL ENDPOINTS ---

@app.get("/")
def root():
    return {"status": "Gamer's Archive API çalışıyor 🚀"}

@app.get("/locale")
def detect_locale(request: Request, lang: str = ""):
    """IP'den ülke algıla ve locale bilgisi döndür. lang ile override edilebilir."""
    if lang and lang in LOCALE_CONFIG:
        locale = LOCALE_CONFIG[lang]
        return {"lang": lang, **locale}
    client_ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    country = get_country_from_ip(client_ip)
    detected_lang = COUNTRY_TO_LANG.get(country, "en")
    locale = LOCALE_CONFIG[detected_lang]
    return {"lang": detected_lang, "detected_country": country, **locale}

@app.get("/search")
def search_game(query: str):
    results = []

    # 1) Steam arama
    try:
        r = requests.get(
            f"https://store.steampowered.com/api/storesearch/?term={query}&l=english&cc=US",
            timeout=10
        ).json()
        steam_items = [
            {**i, "source": "steam"}
            for i in r.get("items", [])
            if "soundtrack" not in i["name"].lower()
            and "dlc" not in i["name"].lower()
            and "demo" not in i["name"].lower()
        ]
        results.extend(steam_items[:5])
    except:
        pass

    # 2) RAWG fallback — Steam'de az sonuç varsa veya hiç yoksa
    if len(results) < 3:
        try:
            rawg_r = requests.get(
                "https://api.rawg.io/api/games",
                params={"key": RAWG_API_KEY, "search": query, "page_size": 6, "search_precise": True},
                timeout=10
            ).json()
            steam_names = {r["name"].lower() for r in results}
            for g in rawg_r.get("results", []):
                if g["name"].lower() not in steam_names:
                    results.append({
                        "id": f"rawg_{g['id']}",
                        "name": g["name"],
                        "tiny_image": g.get("background_image"),
                        "source": "rawg",
                        "rawg_id": g["id"],
                        "rawg_slug": g.get("slug", ""),
                        "metacritic": g.get("metacritic"),
                        "platforms": [p["platform"]["name"] for p in g.get("platforms", [])][:4],
                    })
                if len(results) >= 8:
                    break
        except:
            pass

    return {"results": results[:8]}

@app.get("/game/{app_id}")
def get_game_details(app_id: int):
    result = {}
    try:
        det = requests.get(f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=turkish").json()
        if det[str(app_id)]['success']:
            data = det[str(app_id)]['data']
            result['tags'] = [g['description'] for g in data.get('genres', [])][:5]
            result['name'] = data.get('name', '')
    except:
        pass
    try:
        r = requests.get(f"https://store.steampowered.com/appreviews/{app_id}?json=1&language=all").json()
        total = r["query_summary"]["total_reviews"]
        positive = r["query_summary"]["total_positive"]
        result['steam_score'] = round((positive / total) * 100) if total > 0 else None
    except:
        pass
    try:
        kur = requests.get("https://api.exchangerate-api.com/v4/latest/USD").json()['rates']['TRY']
        result['exchange_rate'] = kur
    except:
        pass
    return result

@app.get("/prices")
def get_prices(name: str):
    result = {}
    try:
        clean = re.sub(r'\(.*?\)|[:™®]', '', name).strip()
        lookup = requests.get(
            "https://api.isthereanydeal.com/games/lookup/v1",
            params={"key": ITAD_API_KEY, "title": clean},
            timeout=5
        ).json()
        if lookup.get('game'):
            game_id = lookup['game']['id']
            prices = requests.post(
                "https://api.isthereanydeal.com/games/prices/v3",
                params={"key": ITAD_API_KEY, "country": "TR"},
                json=[game_id],
                timeout=5
            ).json()
            if prices:
                for deal in prices[0].get('deals', []):
                    if deal.get('shop', {}).get('id') == 16:
                        result['epic'] = f"{deal['price']['amount']:.0f} TL"
                        break
    except:
        pass
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(
            f"https://store.playstation.com/store/api/chihiro/00_09_000/tumbler/TR/tr/999/{requests.utils.quote(name)}?suggested_size=5&mode=game",
            headers=headers, timeout=10
        ).json()
        skip = ['dlc', "friend's pass", 'upgrade', 'müzik', 'soundtrack']
        for l in r.get('links', []):
            n = l.get('name', '').lower()
            if name.lower() in n and not any(w in n for w in skip):
                price = l.get('default_sku', {}).get('display_price', '')
                result['ps_price'] = price if price else None
                result['ps_url'] = f"https://store.playstation.com/tr-tr/search/{requests.utils.quote(name)}"
                result['ps_available'] = True
                break
    except:
        result['ps_available'] = False
    return result

@app.get("/subscriptions")
def check_subscriptions(name: str):
    result = {}
    try:
        r = requests.get(
            "https://catalog.gamepass.com/sigls/v2?id=fdd9e2a7-0fee-49f6-ad69-4354098401ff&language=tr-TR&market=TR",
            timeout=10
        )
        game_ids = [item['id'] for item in r.json() if 'id' in item]
        ids_str = ",".join(game_ids)
        r2 = requests.get(
            f"https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={ids_str}&market=TR&languages=tr-TR&MS-CV=DGU1mcuYo0WMMp",
            timeout=15
        )
        products = r2.json().get('Products', [])
        result['gamepass'] = any(
            name.lower() in p['LocalizedProperties'][0]['ProductTitle'].lower()
            for p in products if p.get('LocalizedProperties')
        )
    except:
        result['gamepass'] = False
    try:
        with open("psplus_games.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        games = data.get("games", [])
        result['psplus'] = any(name.lower() in g.lower() or g.lower() in name.lower() for g in games)
    except:
        result['psplus'] = False
    return result

@app.get("/metacritic")
def get_metacritic(name: str):
    try:
        token = get_igdb_token()
        if not token:
            return {"score": None}
        clean = re.sub(r'[™®]', '', name).strip()
        r = requests.post(
            "https://api.igdb.com/v4/games",
            headers={
                "Client-ID": IGDB_CLIENT_ID,
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/plain"
            },
            data=f'search "{clean}"; fields name,aggregated_rating; limit 5;',
            timeout=10
        )
        for game in r.json():
            if clean.lower() in game['name'].lower() or game['name'].lower() in clean.lower():
                if game.get('aggregated_rating'):
                    return {"score": round(game['aggregated_rating'])}
    except:
        pass
    return {"score": None}

# --- KULLANICI ENDPOINTS ---

def get_country_from_ip(ip: str) -> str:
    try:
        r = requests.get(f"https://ipapi.co/{ip}/country/", timeout=5)
        if r.status_code == 200 and len(r.text.strip()) == 2:
            return r.text.strip()
    except:
        pass
    return "TR"

@app.get("/recommendations")
def get_recommendations(
    score_min: int = 80,
    score_max: int = 100,
    tags: str = "",
    hltb_min: float = 0,
    hltb_max: float = 999,
    archive_names: str = "",
    page_size: int = 40,
):
    try:
        import random
        orderings = ["-metacritic", "-rating", "-added"]
        params = {
            "key": RAWG_API_KEY,
            "metacritic": f"{score_min},{score_max}",
            "page_size": 40,
            "ordering": random.choice(orderings),
            "page": random.randint(1, 3),
        }
        if tags:
            params["tags"] = tags

        r = requests.get("https://api.rawg.io/api/games", params=params, timeout=10).json()
        results = r.get('results', [])
        random.shuffle(results)
        archive_set = set(n.strip().lower() for n in archive_names.split(",") if n.strip())

        output = []
        for oyun in results:
            if len(output) >= 5:
                break
            name = oyun.get('name', '')
            metacritic = oyun.get('metacritic')
            background = oyun.get('background_image', '')
            genres = [g['name'] for g in oyun.get('genres', [])]
            in_archive = name.lower() in archive_set

            if metacritic is None:
                continue
            if not (score_min <= metacritic <= score_max):
                continue

            if hltb_max < 999:
                try:
                    from howlongtobeatpy import HowLongToBeat
                    import re as _re
                    clean = _re.sub(r'\(.*?\)|[:™®]', '', name).strip()
                    hltb_r = HowLongToBeat().search(clean)
                    if hltb_r:
                        sure = max(hltb_r, key=lambda x: x.similarity).main_story
                        if sure and not (hltb_min <= sure <= hltb_max):
                            continue
                except:
                    pass

            output.append({
                "name": name,
                "metacritic": metacritic,
                "background_image": background,
                "genres": genres,
                "in_archive": in_archive,
            })

        return {"results": output}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/users")
def create_or_get_user(request: Request, email: str, display_name: str = "", avatar_url: str = ""):
    try:
        existing = supabase.table("users").select("*").eq("email", email).execute()
        if existing.data:
            return existing.data[0]
        # IP'den ülke algıla
        client_ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
        country = get_country_from_ip(client_ip)
        new_user = supabase.table("users").insert({
            "email": email,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "country": country
        }).execute()
        return new_user.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/{user_id}/games")
def get_user_games(user_id: str):
    try:
        games = supabase.table("games").select("*, categories(name)").eq("user_id", user_id).execute()
        return {"games": games.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/games")
def add_game(game: GameAdd):
    try:
        result = supabase.table("games").insert({
            "user_id": game.user_id,
            "name": game.name,
            "category_id": game.category_id,
            "status": game.status
        }).execute()
        return result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/games/{game_id}")
def update_game(game_id: str, update: GameUpdate):
    try:
        data = {k: v for k, v in update.dict().items() if v is not None}
        if update.status == "completed":
            data["completed_at"] = "now()"
        result = supabase.table("games").update(data).eq("id", game_id).execute()
        return result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/games/{game_id}")
def delete_game(game_id: str):
    try:
        supabase.table("games").delete().eq("id", game_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/{user_id}/categories")
def get_categories(user_id: str):
    try:
        cats = supabase.table("categories").select("*").eq("user_id", user_id).execute()
        return {"categories": cats.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/categories")
def add_category(cat: CategoryAdd):
    try:
        result = supabase.table("categories").insert({
            "user_id": cat.user_id,
            "name": cat.name
        }).execute()
        return result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/psplus_debug")
def psplus_debug(name: str = "hades"):
    games = get_psplus_catalog()
    clean = re.sub(r'\(.*?\)|[:™®]', '', name).strip().lower()
    matches = [g for g in games if clean in g.lower() or g.lower() in clean]
    return {"total": len(games), "matches": matches, "query": clean}


@app.get("/game_full/rawg/{rawg_id}")
def get_game_full_rawg(rawg_id: int, name: str = "", lang: str = "tr"):
    """PS/Nintendo/multi-platform oyunlar için RAWG bazlı detay"""
    result = {"source": "rawg", "steam": "N/A"}
    locale = get_locale_config(lang)
    currency = locale["currency"]
    ps_country = locale["ps_country"]
    ps_lang = locale["ps_lang"]
    ps_locale_str = locale["ps_locale"]

    # Döviz kuru
    try:
        rates = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5).json()["rates"]
        usd_to_local = rates.get(currency, 1)
    except:
        rates = {}
        usd_to_local = 1

    # RAWG detayları
    try:
        g = requests.get(
            f"https://api.rawg.io/api/games/{rawg_id}",
            params={"key": RAWG_API_KEY}, timeout=10
        ).json()
        result["name"] = g.get("name", name)
        result["header_image"] = g.get("background_image", "")
        result["tags"] = [gn["name"] for gn in g.get("genres", [])][:5]
        result["metascore"] = g.get("metacritic")
        result["description"] = re.sub(r"<[^>]+>", "", g.get("description", ""))[:400]
        result["platforms"] = [p["platform"]["name"] for p in g.get("platforms", [])][:6]
        if not name:
            name = result["name"]
    except:
        pass

    # PS Store fiyatı
    if name:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(
                f"https://store.playstation.com/store/api/chihiro/00_09_000/tumbler/{ps_country}/{ps_lang}/999/{requests.utils.quote(name)}?suggested_size=5&mode=game",
                headers=headers, timeout=10
            ).json()
            for l in r.get("links", []):
                n = l.get("name", "").lower()
                clean_name = re.sub(r"\(.*?\)|[:™®]", "", name).strip().lower()
                if clean_name in n and not any(w in n for w in ["dlc", "upgrade", "soundtrack"]):
                    price = l.get("default_sku", {}).get("display_price", "")
                    result["ps_store"] = price if price else None
                    result["ps_url"] = f"https://store.playstation.com/{ps_locale_str}/search/{requests.utils.quote(name)}"
                    break
        except:
            pass

    # Metacritic (IGDB)
    if not result.get("metascore") and name:
        try:
            igdb_token = requests.post(
                f"https://id.twitch.tv/oauth2/token?client_id={IGDB_CLIENT_ID}&client_secret={IGDB_CLIENT_SECRET}&grant_type=client_credentials"
            ).json()["access_token"]
            clean = re.sub(r"\(.*?\)|[:™®]", "", name).strip().lower()
            igdb_r = requests.post(
                "https://api.igdb.com/v4/games",
                headers={"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {igdb_token}"},
                data=f'search "{clean}"; fields name,aggregated_rating; limit 5;'
            ).json()
            for g in igdb_r:
                if clean in g.get("name", "").lower() and g.get("aggregated_rating"):
                    result["metascore"] = round(g["aggregated_rating"])
                    break
        except:
            pass

    # HLTB
    if name:
        try:
            from howlongtobeatpy import HowLongToBeat
            clean = re.sub(r"\(.*?\)|[:™®]", "", name).strip()
            hltb = HowLongToBeat().search(clean)
            if hltb:
                b = max(hltb, key=lambda x: x.similarity)
                def fmt(s):
                    if not s or s <= 0: return None
                    frac = s % 1
                    if frac < 0.25: return f"{int(s)}h"
                    elif frac < 0.75: return f"{int(s)}.5h"
                    else: return f"{int(s)+1}h"
                result["hltb"] = {"main": fmt(b.main_story), "extra": fmt(b.main_extra), "completionist": fmt(b.completionist)}
        except:
            pass

    # PS Plus kontrolü
    try:
        psplus_games = get_psplus_catalog()
        clean_name = re.sub(r"\(.*?\)|[:™®]", "", name).strip().lower()
        result["psplus"] = any(clean_name in g.lower() or g.lower() in clean_name for g in psplus_games)
    except:
        result["psplus"] = False

    result["gamepass"] = False  # Nintendo/PS oyunları Game Pass'te olmaz

    return result

@app.get("/game_full/{app_id}")
def get_game_full(app_id: int, name: str = "", lang: str = "tr"):
    result = {}
    # Curly apostrophe ve benzeri unicode karakterleri normalize et
    name = name.replace('\u2019', "'").replace('\u2018', "'").replace('\u201c', '"').replace('\u201d', '"')
    locale = get_locale_config(lang)
    cc = locale["cc"]
    itad_country = locale["itad_country"]
    ps_country = locale["ps_country"]
    ps_lang = locale["ps_lang"]
    ps_locale_str = locale["ps_locale"]
    currency = locale["currency"]

    # Döviz kurunu bir kez çek
    try:
        rates = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5).json()['rates']
        usd_to_local = rates.get(currency, 1)
    except:
        rates = {}
        usd_to_local = 1

    # Steam detayları (ülke bazlı fiyat için cc parametresi)
    try:
        det = requests.get(
            f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc={cc}&l={locale['lang']}"
        ).json()
        if det[str(app_id)]['success']:
            data = det[str(app_id)]['data']
            result['header_image'] = data.get('header_image', '')
            result['tags'] = [g['description'] for g in data.get('genres', [])][:5]
            result['name'] = data.get('name', '')
            price_data = data.get('price_overview', {})
            if price_data:
                steam_currency = price_data.get('currency', 'USD')
                raw_amount = price_data.get('final', 0) / 100
                if steam_currency == currency:
                    # Steam zaten doğru para biriminde döndü (ör: TRY → TRY)
                    result['steam'] = format_price(raw_amount, locale)
                elif steam_currency == 'USD':
                    f_local = raw_amount * usd_to_local
                    result['steam'] = format_price(f_local, locale, raw_amount)
                else:
                    usd_equiv = raw_amount / rates.get(steam_currency, 1) if rates else None
                    f_local = usd_equiv * usd_to_local if usd_equiv else raw_amount
                    result['steam'] = format_price(f_local, locale, usd_equiv)
    except:
        pass

    # Steam puanı
    try:
        r = requests.get(f"https://store.steampowered.com/appreviews/{app_id}?json=1&language=all").json()
        total = r["query_summary"]["total_reviews"]
        positive = r["query_summary"]["total_positive"]
        if total > 0:
            positive_word = {
                'tr': 'Olumlu', 'de': 'Positiv', 'es': 'Positivo',
                'fr': 'Positif', 'ja': 'ポジティブ', 'en_uk': 'Positive', 'en': 'Positive'
            }.get(lang, 'Positive')
            result['steam_score'] = f"%{round((positive/total)*100)} {positive_word}"
    except:
        pass

    # Epic fiyat (ITAD — ülke bazlı)
    if name:
        try:
            clean = re.sub(r'\(.*?\)|[:™®]', '', name).strip()
            lookup = requests.get(
                "https://api.isthereanydeal.com/games/lookup/v1",
                params={"key": ITAD_API_KEY, "title": clean}, timeout=5
            ).json()
            if lookup.get('game'):
                prices = requests.post(
                    "https://api.isthereanydeal.com/games/prices/v3",
                    params={"key": ITAD_API_KEY, "country": itad_country},
                    json=[lookup['game']['id']], timeout=5
                ).json()
                if prices:
                    for deal in prices[0].get('deals', []):
                        if deal.get('shop', {}).get('id') == 16:
                            amount = deal['price']['amount']
                            deal_currency = deal['price'].get('currency', currency)
                            if deal_currency == 'USD':
                                f_local = amount * usd_to_local
                                result['epic'] = format_price(f_local, locale, amount)
                            else:
                                usd_equiv = amount / rates.get(deal_currency, 1) if rates else None
                                result['epic'] = format_price(amount, locale, usd_equiv)
                            break
        except:
            pass

    # PS Store (ülke bazlı)
    if name:
        # ps_url her zaman set et (fiyat bulunamasa da link çalışsın)
        result['ps_url'] = f"https://store.playstation.com/{ps_locale_str}/search/{requests.utils.quote(name)}"
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(
                f"https://store.playstation.com/store/api/chihiro/00_09_000/tumbler/{ps_country}/{ps_lang}/999/{requests.utils.quote(name)}?suggested_size=5&mode=game",
                headers=headers, timeout=10
            ).json()
            for l in r.get('links', []):
                n = l.get('name', '').lower()
                if name.lower() in n and not any(w in n for w in ['dlc', 'upgrade', 'soundtrack']):
                    price = l.get('default_sku', {}).get('display_price', '')
                    result['ps_store'] = price if price else None
                    break
        except:
            pass

    # Metacritic — önce IGDB, bulamazsa RAWG
    try:
        igdb_token = requests.post(
            f"https://id.twitch.tv/oauth2/token?client_id={IGDB_CLIENT_ID}&client_secret={IGDB_CLIENT_SECRET}&grant_type=client_credentials"
        ).json()['access_token']
        clean = re.sub(r'\(.*?\)|[:™®]', '', name or result.get('name', '')).strip().lower()
        igdb_r = requests.post(
            "https://api.igdb.com/v4/games",
            headers={"Client-ID": IGDB_CLIENT_ID, "Authorization": f"Bearer {igdb_token}"},
            data=f'search "{clean}"; fields name,aggregated_rating; limit 5;'
        ).json()
        for g in igdb_r:
            if clean in g.get('name', '').lower() and g.get('aggregated_rating'):
                result['metascore'] = round(g['aggregated_rating'])
                break
    except:
        pass

    # Metascore hâlâ yoksa RAWG'dan çek
    if not result.get('metascore') and name:
        try:
            clean = re.sub(r'\(.*?\)|[:™®]', '', name).strip()
            clean = clean.replace('\u2019', "'").replace('\u2018', "'")
            rawg_r = requests.get(
                "https://api.rawg.io/api/games",
                params={"key": RAWG_API_KEY, "search": clean, "page_size": 3, "search_precise": True},
                timeout=8
            ).json()
            for g in rawg_r.get('results', []):
                g_name = re.sub(r'\(.*?\)|[:™®]', '', g.get('name', '')).strip().lower()
                if g.get('metacritic') and (clean.lower() in g_name or g_name in clean.lower()):
                    result['metascore'] = g['metacritic']
                    break
        except:
            pass

    # HLTB
    if name:
        try:
            from howlongtobeatpy import HowLongToBeat
            clean = re.sub(r'\(.*?\)|[:™®]', '', name).strip()
            hltb = HowLongToBeat().search(clean)
            if hltb:
                b = max(hltb, key=lambda x: x.similarity)
                def fmt(s):
                    if not s or s <= 0: return None
                    frac = s % 1
                    if frac < 0.25: return f"{int(s)}h"
                    elif frac < 0.75: return f"{int(s)}.5h"
                    else: return f"{int(s)+1}h"
                result['hltb'] = {"main": fmt(b.main_story), "extra": fmt(b.main_extra), "completionist": fmt(b.completionist)}
        except:
            pass

    # Game Pass
    try:
        r = requests.get("https://catalog.gamepass.com/sigls/v2?id=fdd9e2a7-0fee-49f6-ad69-4354098401ff&language=tr-TR&market=TR", timeout=10)
        game_ids = [item['id'] for item in r.json() if 'id' in item]
        ids_str = ",".join(game_ids)
        r2 = requests.get(f"https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={ids_str}&market=TR&languages=tr-TR&MS-CV=DGU1mcuYo0WMMp", timeout=15)
        products = r2.json().get('Products', [])
        result['gamepass'] = any(
            name.lower() in p.get('LocalizedProperties', [{}])[0].get('ProductTitle', '').lower()
            for p in products if p.get('LocalizedProperties')
        )
    except:
        result['gamepass'] = False

    # PS Plus
    try:
        psplus_games = get_psplus_catalog()
        clean_name = re.sub(r'\(.*?\)|[:™®]', '', name).strip().lower()
        result['psplus'] = any(clean_name in g.lower() or g.lower() in clean_name for g in psplus_games)
    except:
        result['psplus'] = False

    return result



class FeedbackRequest(BaseModel):
    type: str  # "oneri" veya "sikayet"
    message: str
    user_email: str = ""

@app.post("/feedback")
def send_feedback(req: FeedbackRequest):
    try:
        gmail_user = os.getenv("GMAIL_USER", "")
        gmail_pass = os.getenv("GMAIL_PASS", "")
        if not gmail_user or not gmail_pass:
            return {"success": False, "error": "Mail config eksik"}

        subject = f"[Gamer's Archive] {'Öneri' if req.type == 'oneri' else 'Şikayet'}"
        body = f"""
Tür: {req.type}
Kullanıcı: {req.user_email or 'Anonim'}

Mesaj:
{req.message}
"""
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = gmail_user
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Resend SDK ile gönder
        resend_key = os.getenv("RESEND_API_KEY", "").strip()
        if not resend_key:
            return {"success": False, "error": "Resend key eksik"}

        resend.api_key = resend_key
        params = {
            "from": "Gamer's Archive <onboarding@resend.dev>",
            "to": [gmail_user],
            "subject": subject,
            "text": body
        }
        email = resend.Emails.send(params)
        print(f"Resend response: {email}")

        return {"success": True}
    except Exception as e:
        import traceback
        print(f"FEEDBACK ERROR: {str(e)}")
        print(traceback.format_exc())
        return {"success": False, "error": str(e)}
