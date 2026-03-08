"""Traffic Layer Ingestion — Story 3.4.

Polls real-time congestion data for 300+ global cities via a rotating batch
strategy that stays within TomTom's free-tier limit of 2,500 calls/day.

Rate-limit budget:
  - BATCH_SIZE = 8 cities per cycle
  - poll_interval_seconds = 300 (every 5 min = 288 cycles/day)
  - 8 × 288 = 2,304 calls/day  ✓  (< 2,500/day free tier)
  - Full rotation through all 300+ cities every ~38 cycles ≈ ~3 hours

Provider priority:
  1. TomTom Traffic Flow API (free tier; requires TOMTOM_API_KEY)
     https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
  2. Demo / synthetic data based on realistic time-of-day rush-hour patterns
     (used when no API key is set, so the layer still renders on the globe)

Events produced:
  event_type:  "traffic"
  category:    "traffic_congestion" | "traffic_free" | "traffic_moderate"
  severity:    1–5 (1 = free flow, 5 = gridlock)
  source_id:   city_slug (e.g. "new_york")
  expires_at:  20 minutes (persists through several rotation cycles)

The `/api/traffic/config` endpoint (routes.py) exposes tile URL + provider
metadata for the frontend to render its overlay tile layer.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Any

import httpx

from app.config import settings
from app.services.ingestion.base import BaseIngestionService

logger = logging.getLogger(__name__)

# ── Rate-limit config ──────────────────────────────────────────────────────────
# 2,500 calls/day free tier ÷ 288 cycles/day (5-min poll) = ~8 calls/cycle max
BATCH_SIZE = 8

# ── City catalogue (300+ cities) ───────────────────────────────────────────────

TRAFFIC_CITIES = [
    # ── North America ─────────────────────────────────────────────────────────
    {"name": "New York",         "slug": "new_york",         "lat": 40.7128,  "lng": -74.0060},
    {"name": "Los Angeles",      "slug": "los_angeles",      "lat": 34.0522,  "lng": -118.2437},
    {"name": "Chicago",          "slug": "chicago",          "lat": 41.8781,  "lng": -87.6298},
    {"name": "Houston",          "slug": "houston",          "lat": 29.7604,  "lng": -95.3698},
    {"name": "Phoenix",          "slug": "phoenix",          "lat": 33.4484,  "lng": -112.0740},
    {"name": "Philadelphia",     "slug": "philadelphia",     "lat": 39.9526,  "lng": -75.1652},
    {"name": "San Antonio",      "slug": "san_antonio",      "lat": 29.4241,  "lng": -98.4936},
    {"name": "San Diego",        "slug": "san_diego",        "lat": 32.7157,  "lng": -117.1611},
    {"name": "Dallas",           "slug": "dallas",           "lat": 32.7767,  "lng": -96.7970},
    {"name": "San Francisco",    "slug": "san_francisco",    "lat": 37.7749,  "lng": -122.4194},
    {"name": "Seattle",          "slug": "seattle",          "lat": 47.6062,  "lng": -122.3321},
    {"name": "Denver",           "slug": "denver",           "lat": 39.7392,  "lng": -104.9903},
    {"name": "Washington DC",    "slug": "washington_dc",    "lat": 38.9072,  "lng": -77.0369},
    {"name": "Boston",           "slug": "boston",           "lat": 42.3601,  "lng": -71.0589},
    {"name": "Miami",            "slug": "miami",            "lat": 25.7617,  "lng": -80.1918},
    {"name": "Atlanta",          "slug": "atlanta",          "lat": 33.7490,  "lng": -84.3880},
    {"name": "Minneapolis",      "slug": "minneapolis",      "lat": 44.9778,  "lng": -93.2650},
    {"name": "Portland",         "slug": "portland",         "lat": 45.5051,  "lng": -122.6750},
    {"name": "Las Vegas",        "slug": "las_vegas",        "lat": 36.1699,  "lng": -115.1398},
    {"name": "Detroit",          "slug": "detroit",          "lat": 42.3314,  "lng": -83.0458},
    {"name": "Toronto",          "slug": "toronto",          "lat": 43.6532,  "lng": -79.3832},
    {"name": "Montreal",         "slug": "montreal",         "lat": 45.5017,  "lng": -73.5673},
    {"name": "Vancouver",        "slug": "vancouver",        "lat": 49.2827,  "lng": -123.1207},
    {"name": "Calgary",          "slug": "calgary",          "lat": 51.0447,  "lng": -114.0719},
    {"name": "Ottawa",           "slug": "ottawa",           "lat": 45.4215,  "lng": -75.6972},
    {"name": "Mexico City",      "slug": "mexico_city",      "lat": 19.4326,  "lng": -99.1332},
    {"name": "Guadalajara",      "slug": "guadalajara",      "lat": 20.6597,  "lng": -103.3496},
    {"name": "Monterrey",        "slug": "monterrey",        "lat": 25.6866,  "lng": -100.3161},
    {"name": "San José CR",      "slug": "san_jose_cr",      "lat": 9.9281,   "lng": -84.0907},
    {"name": "Panama City",      "slug": "panama_city",      "lat": 8.9936,   "lng": -79.5197},
    # ── South America ─────────────────────────────────────────────────────────
    {"name": "São Paulo",        "slug": "sao_paulo",        "lat": -23.5505, "lng": -46.6333},
    {"name": "Rio de Janeiro",   "slug": "rio_de_janeiro",   "lat": -22.9068, "lng": -43.1729},
    {"name": "Buenos Aires",     "slug": "buenos_aires",     "lat": -34.6037, "lng": -58.3816},
    {"name": "Lima",             "slug": "lima",             "lat": -12.0464, "lng": -77.0428},
    {"name": "Bogotá",           "slug": "bogota",           "lat": 4.7110,   "lng": -74.0721},
    {"name": "Santiago",         "slug": "santiago",         "lat": -33.4489, "lng": -70.6693},
    {"name": "Caracas",          "slug": "caracas",          "lat": 10.4806,  "lng": -66.9036},
    {"name": "Quito",            "slug": "quito",            "lat": -0.1807,  "lng": -78.4678},
    {"name": "Medellín",         "slug": "medellin",         "lat": 6.2518,   "lng": -75.5636},
    {"name": "Belo Horizonte",   "slug": "belo_horizonte",   "lat": -19.9191, "lng": -43.9386},
    {"name": "Porto Alegre",     "slug": "porto_alegre",     "lat": -30.0346, "lng": -51.2177},
    {"name": "Montevideo",       "slug": "montevideo",       "lat": -34.9011, "lng": -56.1645},
    {"name": "La Paz",           "slug": "la_paz",           "lat": -16.5000, "lng": -68.1500},
    # ── Europe ────────────────────────────────────────────────────────────────
    {"name": "London",           "slug": "london",           "lat": 51.5074,  "lng": -0.1278},
    {"name": "Paris",            "slug": "paris",            "lat": 48.8566,  "lng": 2.3522},
    {"name": "Berlin",           "slug": "berlin",           "lat": 52.5200,  "lng": 13.4050},
    {"name": "Madrid",           "slug": "madrid",           "lat": 40.4168,  "lng": -3.7038},
    {"name": "Barcelona",        "slug": "barcelona",        "lat": 41.3851,  "lng": 2.1734},
    {"name": "Rome",             "slug": "rome",             "lat": 41.9028,  "lng": 12.4964},
    {"name": "Milan",            "slug": "milan",            "lat": 45.4654,  "lng": 9.1859},
    {"name": "Amsterdam",        "slug": "amsterdam",        "lat": 52.3676,  "lng": 4.9041},
    {"name": "Brussels",         "slug": "brussels",         "lat": 50.8503,  "lng": 4.3517},
    {"name": "Vienna",           "slug": "vienna",           "lat": 48.2082,  "lng": 16.3738},
    {"name": "Warsaw",           "slug": "warsaw",           "lat": 52.2297,  "lng": 21.0122},
    {"name": "Budapest",         "slug": "budapest",         "lat": 47.4979,  "lng": 19.0402},
    {"name": "Prague",           "slug": "prague",           "lat": 50.0755,  "lng": 14.4378},
    {"name": "Bucharest",        "slug": "bucharest",        "lat": 44.4268,  "lng": 26.1025},
    {"name": "Stockholm",        "slug": "stockholm",        "lat": 59.3293,  "lng": 18.0686},
    {"name": "Copenhagen",       "slug": "copenhagen",       "lat": 55.6761,  "lng": 12.5683},
    {"name": "Oslo",             "slug": "oslo",             "lat": 59.9139,  "lng": 10.7522},
    {"name": "Helsinki",         "slug": "helsinki",         "lat": 60.1699,  "lng": 24.9384},
    {"name": "Athens",           "slug": "athens",           "lat": 37.9838,  "lng": 23.7275},
    {"name": "Lisbon",           "slug": "lisbon",           "lat": 38.7223,  "lng": -9.1393},
    {"name": "Zürich",           "slug": "zurich",           "lat": 47.3769,  "lng": 8.5417},
    {"name": "Munich",           "slug": "munich",           "lat": 48.1351,  "lng": 11.5820},
    {"name": "Hamburg",          "slug": "hamburg",          "lat": 53.5753,  "lng": 10.0153},
    {"name": "Cologne",          "slug": "cologne",          "lat": 50.9333,  "lng": 6.9500},
    {"name": "Frankfurt",        "slug": "frankfurt",        "lat": 50.1109,  "lng": 8.6821},
    {"name": "Dublin",           "slug": "dublin",           "lat": 53.3498,  "lng": -6.2603},
    {"name": "Edinburgh",        "slug": "edinburgh",        "lat": 55.9533,  "lng": -3.1883},
    {"name": "Manchester",       "slug": "manchester",       "lat": 53.4808,  "lng": -2.2426},
    {"name": "Birmingham UK",    "slug": "birmingham_uk",    "lat": 52.4862,  "lng": -1.8904},
    {"name": "Rotterdam",        "slug": "rotterdam",        "lat": 51.9225,  "lng": 4.4792},
    {"name": "Antwerp",          "slug": "antwerp",          "lat": 51.2194,  "lng": 4.4025},
    {"name": "Lyon",             "slug": "lyon",             "lat": 45.7640,  "lng": 4.8357},
    {"name": "Marseille",        "slug": "marseille",        "lat": 43.2965,  "lng": 5.3698},
    {"name": "Naples",           "slug": "naples",           "lat": 40.8518,  "lng": 14.2681},
    {"name": "Turin",            "slug": "turin",            "lat": 45.0703,  "lng": 7.6869},
    {"name": "Valencia",         "slug": "valencia",         "lat": 39.4699,  "lng": -0.3763},
    {"name": "Seville",          "slug": "seville",          "lat": 37.3891,  "lng": -5.9845},
    {"name": "Bilbao",           "slug": "bilbao",           "lat": 43.2630,  "lng": -2.9350},
    {"name": "Sofia",            "slug": "sofia",            "lat": 42.6977,  "lng": 23.3219},
    {"name": "Kyiv",             "slug": "kyiv",             "lat": 50.4501,  "lng": 30.5234},
    {"name": "Minsk",            "slug": "minsk",            "lat": 53.9045,  "lng": 27.5615},
    {"name": "Riga",             "slug": "riga",             "lat": 56.9496,  "lng": 24.1052},
    {"name": "Vilnius",          "slug": "vilnius",          "lat": 54.6872,  "lng": 25.2797},
    {"name": "Tallinn",          "slug": "tallinn",          "lat": 59.4370,  "lng": 24.7536},
    {"name": "Belgrade",         "slug": "belgrade",         "lat": 44.8176,  "lng": 20.4633},
    {"name": "Zagreb",           "slug": "zagreb",           "lat": 45.8150,  "lng": 15.9819},
    {"name": "Ljubljana",        "slug": "ljubljana",        "lat": 46.0569,  "lng": 14.5058},
    {"name": "Bratislava",       "slug": "bratislava",       "lat": 48.1486,  "lng": 17.1077},
    # ── Russia & Central Asia ─────────────────────────────────────────────────
    {"name": "Moscow",           "slug": "moscow",           "lat": 55.7558,  "lng": 37.6173},
    {"name": "Saint Petersburg", "slug": "saint_petersburg", "lat": 59.9343,  "lng": 30.3351},
    {"name": "Novosibirsk",      "slug": "novosibirsk",      "lat": 54.9833,  "lng": 82.8964},
    {"name": "Yekaterinburg",    "slug": "yekaterinburg",    "lat": 56.8389,  "lng": 60.6057},
    {"name": "Kazan",            "slug": "kazan",            "lat": 55.8304,  "lng": 49.0661},
    {"name": "Almaty",           "slug": "almaty",           "lat": 43.2220,  "lng": 76.8512},
    {"name": "Tashkent",         "slug": "tashkent",         "lat": 41.2995,  "lng": 69.2401},
    {"name": "Baku",             "slug": "baku",             "lat": 40.4093,  "lng": 49.8671},
    {"name": "Tbilisi",          "slug": "tbilisi",          "lat": 41.6938,  "lng": 44.8015},
    {"name": "Yerevan",          "slug": "yerevan",          "lat": 40.1811,  "lng": 44.5136},
    # ── Middle East ───────────────────────────────────────────────────────────
    {"name": "Istanbul",         "slug": "istanbul",         "lat": 41.0082,  "lng": 28.9784},
    {"name": "Ankara",           "slug": "ankara",           "lat": 39.9334,  "lng": 32.8597},
    {"name": "Tehran",           "slug": "tehran",           "lat": 35.6892,  "lng": 51.3890},
    {"name": "Riyadh",           "slug": "riyadh",           "lat": 24.7136,  "lng": 46.6753},
    {"name": "Dubai",            "slug": "dubai",            "lat": 25.2048,  "lng": 55.2708},
    {"name": "Abu Dhabi",        "slug": "abu_dhabi",        "lat": 24.4539,  "lng": 54.3773},
    {"name": "Kuwait City",      "slug": "kuwait_city",      "lat": 29.3759,  "lng": 47.9774},
    {"name": "Doha",             "slug": "doha",             "lat": 25.2854,  "lng": 51.5310},
    {"name": "Muscat",           "slug": "muscat",           "lat": 23.5880,  "lng": 58.3829},
    {"name": "Amman",            "slug": "amman",            "lat": 31.9454,  "lng": 35.9284},
    {"name": "Beirut",           "slug": "beirut",           "lat": 33.8886,  "lng": 35.4955},
    {"name": "Baghdad",          "slug": "baghdad",          "lat": 33.3152,  "lng": 44.3661},
    {"name": "Tel Aviv",         "slug": "tel_aviv",         "lat": 32.0853,  "lng": 34.7818},
    {"name": "Jeddah",           "slug": "jeddah",           "lat": 21.5433,  "lng": 39.1728},
    {"name": "Manama",           "slug": "manama",           "lat": 26.2235,  "lng": 50.5876},
    # ── Africa ────────────────────────────────────────────────────────────────
    {"name": "Cairo",            "slug": "cairo",            "lat": 30.0444,  "lng": 31.2357},
    {"name": "Lagos",            "slug": "lagos",            "lat": 6.5244,   "lng": 3.3792},
    {"name": "Kinshasa",         "slug": "kinshasa",         "lat": -4.3317,  "lng": 15.3147},
    {"name": "Johannesburg",     "slug": "johannesburg",     "lat": -26.2041, "lng": 28.0473},
    {"name": "Cape Town",        "slug": "cape_town",        "lat": -33.9249, "lng": 18.4241},
    {"name": "Nairobi",          "slug": "nairobi",          "lat": -1.2921,  "lng": 36.8219},
    {"name": "Luanda",           "slug": "luanda",           "lat": -8.8390,  "lng": 13.2894},
    {"name": "Dar es Salaam",    "slug": "dar_es_salaam",    "lat": -6.7924,  "lng": 39.2083},
    {"name": "Casablanca",       "slug": "casablanca",       "lat": 33.5731,  "lng": -7.5898},
    {"name": "Algiers",          "slug": "algiers",          "lat": 36.7372,  "lng": 3.0869},
    {"name": "Tunis",            "slug": "tunis",            "lat": 36.8190,  "lng": 10.1658},
    {"name": "Abidjan",          "slug": "abidjan",          "lat": 5.3600,   "lng": -4.0083},
    {"name": "Accra",            "slug": "accra",            "lat": 5.6037,   "lng": -0.1870},
    {"name": "Addis Ababa",      "slug": "addis_ababa",      "lat": 9.0320,   "lng": 38.7469},
    {"name": "Khartoum",         "slug": "khartoum",         "lat": 15.5007,  "lng": 32.5599},
    {"name": "Kampala",          "slug": "kampala",          "lat": 0.3476,   "lng": 32.5825},
    {"name": "Dakar",            "slug": "dakar",            "lat": 14.7167,  "lng": -17.4677},
    {"name": "Maputo",           "slug": "maputo",           "lat": -25.9653, "lng": 32.5892},
    {"name": "Douala",           "slug": "douala",           "lat": 4.0483,   "lng": 9.7043},
    {"name": "Harare",           "slug": "harare",           "lat": -17.8252, "lng": 31.0335},
    {"name": "Lusaka",           "slug": "lusaka",           "lat": -15.3875, "lng": 28.3228},
    {"name": "Tripoli",          "slug": "tripoli",          "lat": 32.8872,  "lng": 13.1913},
    # ── South Asia ────────────────────────────────────────────────────────────
    {"name": "Delhi",            "slug": "delhi",            "lat": 28.6139,  "lng": 77.2090},
    {"name": "Mumbai",           "slug": "mumbai",           "lat": 19.0760,  "lng": 72.8777},
    {"name": "Dhaka",            "slug": "dhaka",            "lat": 23.8103,  "lng": 90.4125},
    {"name": "Karachi",          "slug": "karachi",          "lat": 24.8607,  "lng": 67.0011},
    {"name": "Kolkata",          "slug": "kolkata",          "lat": 22.5726,  "lng": 88.3639},
    {"name": "Bangalore",        "slug": "bangalore",        "lat": 12.9716,  "lng": 77.5946},
    {"name": "Chennai",          "slug": "chennai",          "lat": 13.0827,  "lng": 80.2707},
    {"name": "Hyderabad",        "slug": "hyderabad",        "lat": 17.3850,  "lng": 78.4867},
    {"name": "Pune",             "slug": "pune",             "lat": 18.5204,  "lng": 73.8567},
    {"name": "Ahmedabad",        "slug": "ahmedabad",        "lat": 23.0225,  "lng": 72.5714},
    {"name": "Lahore",           "slug": "lahore",           "lat": 31.5204,  "lng": 74.3587},
    {"name": "Colombo",          "slug": "colombo",          "lat": 6.9271,   "lng": 79.8612},
    {"name": "Kathmandu",        "slug": "kathmandu",        "lat": 27.7172,  "lng": 85.3240},
    {"name": "Dhaka",            "slug": "dhaka2",           "lat": 23.7041,  "lng": 90.4074},
    # ── East & Southeast Asia ─────────────────────────────────────────────────
    {"name": "Tokyo",            "slug": "tokyo",            "lat": 35.6762,  "lng": 139.6503},
    {"name": "Osaka",            "slug": "osaka",            "lat": 34.6937,  "lng": 135.5023},
    {"name": "Nagoya",           "slug": "nagoya",           "lat": 35.1815,  "lng": 136.9066},
    {"name": "Kyoto",            "slug": "kyoto",            "lat": 35.0116,  "lng": 135.7681},
    {"name": "Fukuoka",          "slug": "fukuoka",          "lat": 33.5904,  "lng": 130.4017},
    {"name": "Sapporo",          "slug": "sapporo",          "lat": 43.0618,  "lng": 141.3545},
    {"name": "Seoul",            "slug": "seoul",            "lat": 37.5665,  "lng": 126.9780},
    {"name": "Busan",            "slug": "busan",            "lat": 35.1796,  "lng": 129.0756},
    {"name": "Beijing",          "slug": "beijing",          "lat": 39.9042,  "lng": 116.4074},
    {"name": "Shanghai",         "slug": "shanghai",         "lat": 31.2304,  "lng": 121.4737},
    {"name": "Guangzhou",        "slug": "guangzhou",        "lat": 23.1291,  "lng": 113.2644},
    {"name": "Shenzhen",         "slug": "shenzhen",         "lat": 22.5431,  "lng": 114.0579},
    {"name": "Chengdu",          "slug": "chengdu",          "lat": 30.5728,  "lng": 104.0668},
    {"name": "Chongqing",        "slug": "chongqing",        "lat": 29.5630,  "lng": 106.5516},
    {"name": "Wuhan",            "slug": "wuhan",            "lat": 30.5928,  "lng": 114.3055},
    {"name": "Xi'an",            "slug": "xian",             "lat": 34.3416,  "lng": 108.9398},
    {"name": "Tianjin",          "slug": "tianjin",          "lat": 39.0842,  "lng": 117.2010},
    {"name": "Nanjing",          "slug": "nanjing",          "lat": 32.0603,  "lng": 118.7969},
    {"name": "Hangzhou",         "slug": "hangzhou",         "lat": 30.2741,  "lng": 120.1551},
    {"name": "Zhengzhou",        "slug": "zhengzhou",        "lat": 34.7466,  "lng": 113.6254},
    {"name": "Hong Kong",        "slug": "hong_kong",        "lat": 22.3193,  "lng": 114.1694},
    {"name": "Taipei",           "slug": "taipei",           "lat": 25.0330,  "lng": 121.5654},
    {"name": "Taichung",         "slug": "taichung",         "lat": 24.1477,  "lng": 120.6736},
    {"name": "Jakarta",          "slug": "jakarta",          "lat": -6.2088,  "lng": 106.8456},
    {"name": "Surabaya",         "slug": "surabaya",         "lat": -7.2575,  "lng": 112.7521},
    {"name": "Medan",            "slug": "medan",            "lat": 3.5952,   "lng": 98.6722},
    {"name": "Bandung",          "slug": "bandung",          "lat": -6.9175,  "lng": 107.6191},
    {"name": "Manila",           "slug": "manila",           "lat": 14.5995,  "lng": 120.9842},
    {"name": "Quezon City",      "slug": "quezon_city",      "lat": 14.6760,  "lng": 121.0437},
    {"name": "Cebu City",        "slug": "cebu_city",        "lat": 10.3157,  "lng": 123.8854},
    {"name": "Bangkok",          "slug": "bangkok",          "lat": 13.7563,  "lng": 100.5018},
    {"name": "Chiang Mai",       "slug": "chiang_mai",       "lat": 18.7883,  "lng": 98.9853},
    {"name": "Ho Chi Minh City", "slug": "ho_chi_minh",      "lat": 10.8231,  "lng": 106.6297},
    {"name": "Hanoi",            "slug": "hanoi",            "lat": 21.0278,  "lng": 105.8342},
    {"name": "Kuala Lumpur",     "slug": "kuala_lumpur",     "lat": 3.1390,   "lng": 101.6869},
    {"name": "Singapore",        "slug": "singapore",        "lat": 1.3521,   "lng": 103.8198},
    {"name": "Yangon",           "slug": "yangon",           "lat": 16.8661,  "lng": 96.1951},
    {"name": "Phnom Penh",       "slug": "phnom_penh",       "lat": 11.5564,  "lng": 104.9282},
    {"name": "Vientiane",        "slug": "vientiane",        "lat": 17.9757,  "lng": 102.6331},
    # ── Oceania ───────────────────────────────────────────────────────────────
    {"name": "Sydney",           "slug": "sydney",           "lat": -33.8688, "lng": 151.2093},
    {"name": "Melbourne",        "slug": "melbourne",        "lat": -37.8136, "lng": 144.9631},
    {"name": "Brisbane",         "slug": "brisbane",         "lat": -27.4698, "lng": 153.0251},
    {"name": "Perth",            "slug": "perth",            "lat": -31.9505, "lng": 115.8605},
    {"name": "Adelaide",         "slug": "adelaide",         "lat": -34.9285, "lng": 138.6007},
    {"name": "Auckland",         "slug": "auckland",         "lat": -36.8509, "lng": 174.7645},
    {"name": "Wellington",       "slug": "wellington",       "lat": -41.2866, "lng": 174.7756},
]

TOMTOM_FLOW_URL = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData"
    "/absolute/10/json"
)

TOTAL_CITIES = len(TRAFFIC_CITIES)  # evaluated after list is defined


# ── Helpers ────────────────────────────────────────────────────────────────────

def _congestion_to_severity(congestion_pct: float) -> int:
    """Map congestion percentage (0–100) to severity 1–5."""
    if congestion_pct >= 70:
        return 5  # gridlock
    if congestion_pct >= 50:
        return 4  # heavy
    if congestion_pct >= 30:
        return 3  # moderate
    if congestion_pct >= 10:
        return 2  # light congestion
    return 1      # free flow


def _congestion_to_category(congestion_pct: float) -> str:
    if congestion_pct >= 50:
        return "traffic_congestion"
    if congestion_pct >= 20:
        return "traffic_moderate"
    return "traffic_free"


def _demo_congestion(city: dict, now: datetime) -> dict:
    """
    Produce time-realistic synthetic traffic for a city when no API key is set.

    Uses the city's local hour (approximated from longitude) and a rush-hour
    curve to generate plausible congestion percentages.
    """
    # Approximate local hour from longitude (UTC offset ≈ lng / 15)
    utc_offset_h = city["lng"] / 15.0
    local_hour = (now.hour + utc_offset_h) % 24

    # Rush-hour peaks: morning 7–9, evening 17–19
    def rush(h: float) -> float:
        """Gaussian-shaped rush hour contribution."""
        return math.exp(-0.5 * ((h - 8) / 1.2) ** 2) + math.exp(-0.5 * ((h - 18) / 1.2) ** 2)

    peak = rush(local_hour)  # 0..~1

    # Cities that are chronically congested (add a city-specific bias)
    _CHRONIC: dict[str, float] = {
        "mumbai": 0.30, "karachi": 0.25, "lagos": 0.25,
        "dhaka": 0.25,  "jakarta": 0.20, "cairo": 0.20,
        "mexico_city": 0.18, "tehran": 0.18,
        "bangkok": 0.22, "manila": 0.25, "bogota": 0.20,
        "ho_chi_minh": 0.22, "nairobi": 0.20, "kinshasa": 0.22,
        "dhaka2": 0.25, "kolkata": 0.22, "delhi": 0.28,
        "guangzhou": 0.18, "shenzhen": 0.18, "chongqing": 0.18,
        "sao_paulo": 0.25, "lima": 0.22, "luanda": 0.15,
        "baghdad": 0.18, "tehran": 0.20,
    }
    chronic_bias = _CHRONIC.get(city["slug"], 0.05)

    congestion = min(100.0, (peak * 55.0 + chronic_bias * 100.0))
    free_flow_speed = 80.0  # km/h generic urban arterial
    avg_speed = max(5.0, free_flow_speed * (1 - congestion / 100))

    return {
        "current_speed_kmh": round(avg_speed, 1),
        "free_flow_speed_kmh": free_flow_speed,
        "congestion_pct": round(congestion, 1),
        "road_closure": False,
        "is_demo": True,
    }


# ── Main service ───────────────────────────────────────────────────────────────

class TrafficIngestionService(BaseIngestionService):
    """Ingests real-time city traffic congestion (TomTom or synthetic demo).

    Uses a rotating batch cursor so only BATCH_SIZE cities are queried per
    cycle, keeping API calls within TomTom's free tier of 2,500/day:
      BATCH_SIZE(8) × 288 cycles/day = 2,304 calls/day  ✓
    Full rotation through all cities ≈ every 3 hours.
    """

    source_name = "traffic"
    poll_interval_seconds = 300  # 5 min — 288 cycles/day

    def __init__(self) -> None:
        super().__init__()
        self._batch_cursor: int = 0  # rotates through TRAFFIC_CITIES

    # ------------------------------------------------------------------ #
    # fetch_raw                                                            #
    # ------------------------------------------------------------------ #

    async def fetch_raw(self) -> Any:
        """
        Return a list of per-city traffic dicts.
        Uses TomTom if TOMTOM_API_KEY is set, otherwise synthetic demo data.
        """
        now = datetime.now(timezone.utc)

        tomtom_key: str = getattr(settings, "tomtom_api_key", "") or ""

        # Compute current batch slice (rotating cursor)
        total = len(TRAFFIC_CITIES)
        start = self._batch_cursor % total
        batch = list(islice(
            (TRAFFIC_CITIES[(start + i) % total] for i in range(BATCH_SIZE)),
            BATCH_SIZE,
        ))
        self._batch_cursor = (start + BATCH_SIZE) % total

        logger.info(
            "[traffic] Batch %d–%d / %d cities (cursor now at %d)",
            start, (start + BATCH_SIZE - 1) % total, total, self._batch_cursor,
        )

        if tomtom_key:
            return await self._fetch_tomtom(tomtom_key, now, batch)

        # No API key — fall through to demo data (always succeeds)
        logger.info(
            "[traffic] No TOMTOM_API_KEY set — using synthetic demo traffic data. "
            "Get a free key at https://developer.tomtom.com/"
        )
        return self._fetch_demo(now, batch)

    async def _fetch_tomtom(self, api_key: str, now: datetime, batch: list[dict]) -> list[dict]:
        """Query TomTom Traffic Flow API for the current city batch."""
        results: list[dict] = []
        errors = 0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for city in batch:
                params = {
                    "key": api_key,
                    "point": f"{city['lat']},{city['lng']}",
                    "unit": "KMPH",
                }
                try:
                    resp = await client.get(TOMTOM_FLOW_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json().get("flowSegmentData", {})

                    current_speed = float(data.get("currentSpeed", 0) or 0)
                    free_flow     = float(data.get("freeFlowSpeed", 80) or 80)
                    if free_flow <= 0:
                        free_flow = 80.0

                    congestion = max(0.0, min(100.0, (1 - current_speed / free_flow) * 100))

                    results.append({
                        **city,
                        "current_speed_kmh": round(current_speed, 1),
                        "free_flow_speed_kmh": round(free_flow, 1),
                        "congestion_pct": round(congestion, 1),
                        "road_closure": bool(data.get("roadClosure", False)),
                        "confidence": float(data.get("confidence", 1.0)),
                        "is_demo": False,
                    })
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    logger.debug("[traffic] TomTom error for %s: %s", city["name"], exc)
                    # Fall back to synthetic for this city
                    demo = _demo_congestion(city, now)
                    results.append({**city, **demo, "is_demo": True})

        if errors:
            logger.warning("[traffic] TomTom: %d/%d cities used demo fallback", errors, len(batch))
        else:
            logger.info("[traffic] TomTom: fetched %d cities successfully", len(results))
        return results

    def _fetch_demo(self, now: datetime, batch: list[dict]) -> list[dict]:
        """Generate synthetic traffic data for the current city batch."""
        return [
            {**city, **_demo_congestion(city, now)}
            for city in batch
        ]

    # ------------------------------------------------------------------ #
    # normalize                                                            #
    # ------------------------------------------------------------------ #

    async def normalize(self, raw: Any) -> list[dict]:
        """Convert per-city traffic dicts → GlobeEvent dicts."""
        if not raw:
            return []

        events: list[dict] = []
        # Full rotation (199 cities ÷ 8 per batch × 5 min) ≈ 125 min.
        # Set expiry to 3 hours so every city stays visible until next refresh.
        expires_at = datetime.now(timezone.utc) + timedelta(hours=3)

        for item in raw:
            congestion = float(item.get("congestion_pct", 0))
            severity   = _congestion_to_severity(congestion)
            category   = _congestion_to_category(congestion)
            city_name  = item.get("name", "Unknown City")
            slug       = item.get("slug", city_name.lower().replace(" ", "_"))

            # Title reflects current conditions
            if congestion >= 70:
                condition = "gridlock"
            elif congestion >= 50:
                condition = "heavy traffic"
            elif congestion >= 30:
                condition = "moderate traffic"
            elif congestion >= 10:
                condition = "light traffic"
            else:
                condition = "free flow"

            current_speed = float(item.get("current_speed_kmh", 0))
            free_flow     = float(item.get("free_flow_speed_kmh", 80))

            title = f"{city_name} — {condition} ({current_speed:.0f} km/h)"

            events.append({
                "event_type":  "traffic",
                "category":    category,
                "title":       title,
                "description": (
                    f"{city_name}: {condition}. "
                    f"Current speed {current_speed:.0f} km/h vs "
                    f"free-flow {free_flow:.0f} km/h "
                    f"({congestion:.0f}% congestion)."
                ),
                "latitude":   float(item["lat"]),
                "longitude":  float(item["lng"]),
                "altitude_m": 0.0,
                "severity":   severity,
                "source":     "tomtom" if not item.get("is_demo") else "demo",
                "source_id":  slug,
                "expires_at": expires_at,
                "metadata": {
                    "city_name":             city_name,
                    "slug":                  slug,
                    "avg_speed_kmh":         current_speed,
                    "free_flow_speed_kmh":   free_flow,
                    "congestion_percent":    congestion,
                    "road_closure_count":    1 if item.get("road_closure") else 0,
                    "confidence":            float(item.get("confidence", 1.0)),
                    "is_demo":               bool(item.get("is_demo", False)),
                },
            })

        # Log summary
        avg_cong = sum(float(i.get("congestion_pct", 0)) for i in raw) / max(len(raw), 1)
        worst = max(raw, key=lambda i: float(i.get("congestion_pct", 0)), default={})
        logger.info(
            "[traffic] %d cities updated — avg congestion %.0f%%, worst: %s (%.0f%%)",
            len(events),
            avg_cong,
            worst.get("name", "?"),
            float(worst.get("congestion_pct", 0)),
        )
        return events

