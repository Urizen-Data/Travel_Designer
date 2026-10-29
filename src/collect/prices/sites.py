"""Реестр источников цен по курортам.

Каждый курорт добавлен отдельной записью, т.к. сайты различаются структурой.
`urls` — кандидатные адреса (официальный сайт или страница цен), которые
пробует общий краулер scrape_prices.py.
"""
from __future__ import annotations

# (resort_id, name, [кандидатные URL])
SITES: list[tuple[str, str, list[str]]] = [
    ("R001", "Роза Хутор", ["https://rosakhutor.com/tickets-and-passes/ski-passes/"]),
    ("R002", "Красная Поляна", ["https://skipasskp.ru/skipass-ceny-kp"]),
    ("R003", "Газпром Поляна", ["https://polyana-ski.ru/"]),
    ("R004", "Шерегеш", ["https://gesh.ru/sheregesh/skipass/"]),
    ("R005", "Архыз", ["https://arhyz-resort.ru/"]),
    ("R006", "Домбай", ["https://dombay.ru/", "https://dombay.info/"]),
    ("R007", "Эльбрус", ["https://resort-elbrus.ru/", "https://allslopes.ru/elbrus/skipass"]),
    ("R008", "Чегет", ["https://cheget.ru/", "https://cheget.su/"]),
    ("R009", "Мамисон", ["https://mamison.ru/"]),
    ("R010", "Цей", ["https://tsey.ru/"]),
    ("R011", "Манжерок", ["https://manzherok.ru/"]),
    ("R012", "Телецкий", ["https://teletskiy.ru/"]),
    ("R013", "Большой Вудъявр", ["https://bolshoy-vudyavr.ru/"]),
    ("R014", "Кукисвумчорр", ["https://kukisvumchorr.ru/prices"]),
    ("R015", "КолаСпортЛэнд", ["https://kolasportland.ru/"]),
    ("R016", "Горный воздух", ["https://ski-gv.ru/", "https://gorniyvozduh.ru/"]),
    ("R017", "Холдоми", ["https://holdomi.ru/"]),
    ("R018", "Морозная гора", ["https://moroznaya.ru/"]),
    ("R019", "Бобровый лог", ["https://bobrovylog.ru/"]),
    ("R020", "Соболиная гора", ["https://sobolinaya.ru/"]),
    ("R021", "Гора Белая", ["https://gorabelaya.ru/"]),
    ("R022", "Евразия", ["https://euroasia.su/cable-car-fares/"]),
    ("R023", "Аджигардак", ["https://adzhigardak.ru/"]),
    ("R024", "Солнечная долина", ["https://dolina.su/"]),
    ("R025", "Завьялиха", ["https://zavyaliha.ru/"]),
    ("R026", "Абзаково", ["https://abzakovo.com/"]),
    ("R027", "Мраткино", ["https://mratkino.ru/"]),
    ("R028", "Губаха", ["https://gubakha.net/", "https://gubakha.info/"]),
    ("R029", "Игора", ["https://igora.ru/"]),
    ("R030", "Сорочаны", ["https://sorochany.ru/"]),
    ("R031", "Красная Глинка", ["https://krasnaya-glinka.ru/"]),
    ("R032", "Гладенькая", ["https://ski-gladenkaya.ru/ski/sky_pass"]),
]

# Вручную подтверждённые цены (взрослый, 1 день). Сезон 2025/26 — заменить при
# публикации тарифов 2026/27.
VERIFIED: dict[str, dict] = {
    "R004": {"min": 3100, "max": 3100, "url": "https://gesh.ru/sheregesh/skipass/", "season": "2025/26"},
    "R014": {"min": 2000, "max": 2000, "url": "https://kukisvumchorr.ru/prices", "season": "2025/26"},
}
