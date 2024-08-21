from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import messagebox
import sqlite3
import locale
from datetime import datetime
from lxml import html
import requests
import re
import pandas as pd
import folium
import time
from geopy.geocoders import Nominatim


def scrape_olx(url, city, price_from, price_to, rooms_url, furniture, area_from, area_to, page_number):
    created_url = (f'{url}{city}/?page={page_number}&search%5Bfilter_float_price:from%5D={price_from}&search%5Bfilter_float_price:to%5D={price_to}'
                   f'{rooms_url}&search%5Bfilter_enum_furniture%5D={furniture}'
                   f'&search%5Bfilter_float_m:from%5D={area_from}&search%5Bfilter_float_m:to%5D={area_to}')
    page = requests.get(created_url)
    soup = BeautifulSoup(page.content, 'lxml')
    offers = soup.find_all('a', class_='css-z3gu2d')
    hrefs = []
    for offer in offers:
        href = offer.get('href')
        if re.escape('otodom') not in href:
            hrefs.append(f"https://www.olx.pl/{href}")

    return hrefs


def load_street_names(file_path):
    df = pd.read_csv(file_path)
    street_names = df['Street'].astype(str).tolist()
    return street_names


def street_patterns(street_names):
    patterns = {}
    prefixes = ['ulicy', 'ulica', 'ul', 'ul.', 'alei', 'aleja', 'al', 'al.', 'os.', 'os', 'osiedle', 'osiedlu']

    for street in street_names:
        base = street
        base2 = street.split()[-1]

        base_variants = [
            base,
            base2,
            base2 + 'a',
            base2[:-1] + 'ej',
            base2[:-1] + 'iej',
            base2[:-1] + 'ą',
            base2[:-1] + 'i',
            base2[:-1] + 'im'
        ]

        for prefix in prefixes:
            for variant in base_variants:
                pattern = r'\b' + re.escape(prefix.strip() + ' ' + variant) + r'\b'
                if len(base2) > 3:
                    patterns[r'\b' + re.escape(prefix.strip() + variant) + r'\b'] = base

                patterns[pattern] = base
    return patterns



def get_street_coordinates(c, prefix, street_name, city='Kraków', country='Polska'):
    # Replace certain words in the prefix
    replacements = {
        "ulicy": "",
        "ulica": "",
        "ul.": "",
        "ul": "",
        "alei": "al.",
        "osiedlu": "os.",
        "osiedle": "os.",
        "aleja": "al.",
        "osiedla": "os.",
        "al": "al.",
        "os": "os."
    }
    prefix = prefix.lower().strip().split(".")[0]
    for old_word, new_word in replacements.items():
        prefix = prefix.replace(old_word, new_word)

    # Check if the coordinates are already stored in the database
    coordinates = get_street_coordinates_from_db(c, street_name)
    if coordinates and None not in coordinates:
        return coordinates

    # If not found in database, perform geocoding
    geolocator = Nominatim(user_agent='street_marker')
    search_name = f"{prefix} {street_name} {city}"
    try:
        location = geolocator.geocode(search_name.strip())
        if location:
            return location.latitude, location.longitude
        else:
            print(f"Not Found: {prefix} {street_name}")
            return None, None
    except Exception as e:
        print(f"Error finding {prefix} {street_name}: {e}")
        return None, None


def mark_streets(c, street_names_with_prefixes_and_hrefs, city='Kraków', country='Polska'):
    # Initialize the map centered around Kraków
    streets_map = folium.Map(location=[50.0647, 19.9450], zoom_start=13)

    # Dictionary to keep track of URLs associated with each street and prefix combination
    street_hrefs = {}
    for prefix, street_name, href in street_names_with_prefixes_and_hrefs:
        key = (prefix, street_name)
        if key not in street_hrefs:
            street_hrefs[key] = []
        street_hrefs[key].append(href)

    for (prefix, street_name), hrefs in street_hrefs.items():
        # Fetch all coordinates for the street from the database
        c.execute("SELECT latitude, longitude FROM offers WHERE street = ? AND city = ?", (street_name, city))
        coordinates_list = c.fetchall()

        if coordinates_list:
            for lat, lon in coordinates_list:
                if lat is not None and lon is not None:
                    # Create a popup with the street name and associated URLs
                    popup_content = f"{prefix} {street_name}<br>" + "<br>".join(
                        [f'<a href="{href}" target="_blank">{i + 1}</a>' for i, href in enumerate(hrefs)])

                    # Add a marker to the map at each set of coordinates
                    folium.Marker([lat, lon], popup=popup_content).add_to(streets_map)
        else:
            print(f"Coordinates not found for street: {prefix} {street_name}")

    # Save the map to an HTML file
    streets_map.save('streets.html')


def get_data(hrefs, city, street_patterns):
    df = pd.read_csv('cleaned_sample.csv', names=['Street', 'District'])

    for i in range(len(hrefs)):
        page = requests.get(hrefs[i])
        soup = BeautifulSoup(page.content, 'lxml')
        tree = html.fromstring(page.content)

        data = soup.find_all('p', class_='css-b5m1rv')
        data = [d.get_text() for d in data if d is not None and len(d) > 0]

        price2 = 0
        area = 0
        rooms = 0
        for d in data:
            if 'Powierzchnia' in d:
                area = re.search(r'\d+', d)
                if area:
                    area = area.group()

            if 'Liczba pokoi' in d:
                if 'Kawalerka' in d.strip():
                    rooms = 1
                else:
                    rooms = re.search(r'\d+', d)
                    if rooms:
                        rooms = rooms.group()

            price2 = 0
            if 'Czynsz' in d:
                price2 = re.search(r'\d+', d)
                if price2:
                    price2 = price2.group()
                else:
                    price2 = 0

        # price
        price1 = 0
        price_data1 = tree.xpath('/html/body/div[1]/div[2]/div/div[2]/div[3]/div[2]/div[1]/div/div[3]/div/div/h3')
        if price_data1:
            price1_text = price_data1[0].text_content()
            price1 = re.findall(r'\d+', price1_text)
            if price1:
                price1 = ''.join(price1)
            else:
                price1 = 0
        price = int(price1) + int(price2)

        # date
        date_found = tree.xpath('/html/body/div[1]/div[2]/div/div[2]/div[3]/div[2]/div[1]/div/div[1]/span/span')
        if date_found:
            date_found = date_found[0].text_content().lower()
            if 'dzisiaj' in date_found:
                date = datetime.now().date()
            else:
                date = datetime.strptime(date_found, '%d %B %Y')
            date = date.strftime('%Y-%m-%d')
        else:
            date = None

        # title
        title_data = tree.xpath('/html/body/div[1]/div[2]/div/div[2]/div[3]/div[2]/div[1]/div/div[2]/h4')
        if title_data:
            title = title_data[0].text_content()
        else:
            title = None

        text_of_offer = tree.xpath('/html/body/div[1]/div[2]/div/div[2]/div[3]/div[1]/div[2]/div[4]/div')
        if text_of_offer:
            text_of_offer = text_of_offer[0].text_content()
            if title:
                text_of_offer += title
        else:
            text_of_offer = title if title else ""


        streets_with_prefixes = []
        for pattern, base in street_patterns.items():
            match = re.search(pattern, text_of_offer, re.IGNORECASE)
            if match:
                base = base.replace("\\", "")
                prefix = match.group().split()[0]
                streets_with_prefixes.append((base, prefix))

        if not streets_with_prefixes:
            streets_with_prefixes.append((None, None))

        district = None
        for street, prefix in streets_with_prefixes:
            if street:
                district_data = df.loc[
                    df['Street'].str.lower().str.strip() == street.lower().strip(), 'District'].values
                if district_data.size > 0:
                    district = district_data[0]
                    break

        is_available = True
        return title, str(city), int(price), int(area), int(rooms), district, streets_with_prefixes[0][1], streets_with_prefixes[0][0], hrefs[i], date, is_available

def check_offer_availability(url):
    try:
        response = requests.get(url)
        return response.status_code == 200
    except requests.RequestException:
        return False


def update_offer_availability(c, url, availability):
    c.execute("UPDATE offers SET is_available = ? WHERE url = ?", (availability, url))


def create_database(c):
    # c.execute('''DROP TABLE IF EXISTS offers''')
    c.execute('''CREATE TABLE IF NOT EXISTS offers
             (title TEXT, city TEXT, price INTEGER, area INTEGER, rooms INTEGER, district TEXT, street_prefix TEXT, street TEXT, url TEXT, date TEXT, is_available BOOLEAN, latitude REAL, longitude REAL)''')

def insert_data(c, title, city, price, area, rooms, district, street_prefix, street, url, date, is_available, latitude=None, longitude=None):
    c.execute("INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (title, city, price, area, rooms, district, street_prefix, street, url, date, is_available, latitude, longitude))


def get_street_coordinates_from_db(c, street_name):
    c.execute("SELECT latitude, longitude FROM offers WHERE street = ? LIMIT 1", (street_name,))
    return c.fetchone()


def url_exists(c, url):
    c.execute("SELECT 1 FROM offers WHERE url = ?", (url,))
    return c.fetchone() is not None


def fetch_offers(c):
    c.execute("SELECT street_prefix, street, url FROM offers")
    return c.fetchall()


def check_data(c):
    c.execute("SELECT url FROM offers WHERE is_available = 1")
    urls = c.fetchall()
    check_avail = input("Should I check if the offers are still available? (yes, no) ")
    if check_avail.lower() == 'yes':
        for url in urls:
            is_available = check_offer_availability(url[0])
            if not is_available:
                update_offer_availability(c, url[0], 0)

    c.execute("SELECT * FROM offers")
    rows = c.fetchall()
    for row in rows:
        print(row)


def get_offers_from_db(c, city, rooms, price_from, price_to, furniture, area_from, area_to, is_available):
    replace_rooms = {'one': 1, 'two': 2, 'three': 3, 'four': 4}
    try:
        rooms = [replace_rooms[room.strip().lower()] for room in rooms if room.strip().lower() in replace_rooms]
    except KeyError as e:
        print(f"Invalid room type provided: {e}")
        return []
    placeholders = ','.join('?' for _ in rooms)

    sql = f"""
    SELECT * FROM offers
    WHERE city = ?
    AND rooms IN ({placeholders})
    AND price >= ?
    AND price <= ?
    AND area >= ?
    AND area <= ?
    AND is_available = ?
    """

    params = [city, *rooms, int(price_from), int(price_to), int(area_from), int(area_to), is_available]
    c.execute(sql, params)
    return c.fetchall()


def load_patterns_from_file(file_path):
    with open(file_path, 'r') as f:
        patterns = eval(f.read())
    return patterns


def clean_database(c):
    c.execute("DELETE FROM offers WHERE area < 1 AND rooms < 1")


def main():
    locale.setlocale(locale.LC_TIME, 'pl_PL.UTF-8')

    city = input('Enter city without polish letters: ')
    rooms_number = input('Enter number of rooms: (one, two, three, four; you can choose multiple options using ",") ')
    rooms = rooms_number.split(',')
    rooms_url = '?'
    for i, room in enumerate(rooms):
        rooms_url += f'search%5B[filter_enum_rooms][{i}]={room.strip()}'
        if i < len(rooms) - 1:
            rooms_url += '&'
    price_from = input('Enter minimum price: ')
    price_to = input('Enter maximum price: ')
    furniture = input('Furnished? (yes, no) ')
    area_from = input('Enter minimum area: ')
    area_to = input('Enter maximum area: ')

    url = 'https://www.olx.pl/nieruchomosci/mieszkania/wynajem/'
    hrefs = []
    page = 1
    while True:
        try:
            if page > 3:
                break
            hrefs += scrape_olx(url, city, price_from, price_to, rooms_url, furniture, area_from, area_to, page)
            page += 1
        except:
            break


    city_replacements = {'krakow': 'Kraków', 'warszawa': 'Warszawa', 'lodz': 'Łódź', 'szczecin': 'Szczecin',
                         'poznan': 'Poznań', 'wroclaw': 'Wrocław', 'gdansk': 'Gdańsk', 'katowice': 'Katowice',
                         'bydgoszcz': 'Bydgoszcz', 'torun': 'Toruń', 'bialystok': 'Białystok', 'rzeszow': 'Rzeszów'}
    for key, value in city_replacements.items():
        city = city.replace(key, value)

    hrefs = list(set(hrefs))
    # street_names = load_street_names('cleaned_sample.csv')

    patterns = load_patterns_from_file("patterns.txt")

    try:
        conn = sqlite3.connect('olx_offers.db')
        c = conn.cursor()
        create_database(c)

        clean_database(c)

        for href in hrefs:
            if url_exists(c, href):
                continue
            extracted_data = get_data([href], city, patterns)

            if extracted_data is not None:
                if extracted_data[6] and extracted_data[7] is not None:
                    insert_data(c, *extracted_data, *get_street_coordinates(c, extracted_data[6], extracted_data[7]))
                else:
                    insert_data(c, *extracted_data, None, None)

        c.execute("SELECT url FROM offers")
        urls = c.fetchall()
        for url in urls:
            is_available = check_offer_availability(url[0])
            update_offer_availability(c, url[0], is_available)

        check_data(c)

        offers = get_offers_from_db(c, city, rooms, price_from, price_to, furniture, area_from, area_to, 1)
        streets_with_prefixes_and_hrefs = [(offer[6], offer[7], offer[8]) for offer in offers if offer[7] is not None]
        mark_streets(c, streets_with_prefixes_and_hrefs)

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")

    except requests.RequestException as e:
        print(f"Request error: {e}")

    except Exception as e:
        print(f"An error {e} occurred")

    finally:
        if conn:
            conn.commit()
            conn.close()


if __name__ == '__main__':
    main()
