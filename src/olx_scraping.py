from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import sqlite3
import locale
from datetime import datetime
from lxml import html
import requests
import re
import pandas as pd
import folium
from folium.plugins import Draw
from geopy.distance import geodesic
import time
from geopy.geocoders import Nominatim
import webbrowser
from tkinter import simpledialog


CITIES = ["Kraków", "Warszawa", "Łódź", "Szczecin", "Poznań", "Wrocław", "Gdańsk", "Katowice", "Bydgoszcz", "Toruń", "Białystok", "Rzeszów"]

CITY_REPLACEMENTS = {'krakow': 'Kraków', 'warszawa': 'Warszawa', 'lodz': 'Łódź', 'szczecin': 'Szczecin',
                     'poznan': 'Poznań', 'wroclaw': 'Wrocław', 'gdansk': 'Gdańsk', 'katowice': 'Katowice',
                     'bydgoszcz': 'Bydgoszcz', 'torun': 'Toruń', 'bialystok': 'Białystok', 'rzeszow': 'Rzeszów'}

def scrape_olx(url, city, price_from, price_to, rooms_url, furniture, area_from, area_to, page_number):
    print(f"{url}, {city}, {price_from}, {price_to}, {rooms_url}, {furniture}, {area_from}, {area_to}, {page_number}")
    created_url = (
        f'{url}{city}/?page={page_number}&search%5Bfilter_float_price%3Afrom%5D={price_from}&search%5Bfilter_float_price%3Ato%5D={price_to}'
        f'{rooms_url}&search%5Bfilter_enum_furniture%5D%5B0%5D={furniture}'
        f'&search%5Bfilter_float_m%3Afrom%5D={area_from}&search%5Bfilter_float_m%3Ato%5D={area_to}')
    print(created_url)
    page = requests.get(created_url)
    soup = BeautifulSoup(page.content, 'lxml')
    offers = soup.find_all('a', class_='css-z3gu2d')
    hrefs = []
    for offer in offers:
        href = offer.get('href')
        if 'otodom' not in href:
            hrefs.append(f"https://www.olx.pl/{href}")

    hrefs = list(set(hrefs))
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

    # Enable the Draw feature for circle
    draw = Draw(export=True, draw_options={'circle': True, 'polygon': False, 'polyline': False, 'rectangle': False})
    draw.add_to(streets_map)

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


    map_file = 'streets.html'

    # Save the map to an HTML file
    streets_map.save(map_file)

    webbrowser.open(map_file)


def filter_offers_within_circle(offers, center_lat, center_lon, radius_km):
    filtered_offers = []
    for offer in offers:
        offer_lat, offer_lon = offer[5], offer[6]  # Assuming offer[5] is latitude and offer[6] is longitude
        if offer_lat is not None and offer_lon is not None:
            distance = geodesic((center_lat, center_lon), (offer_lat, offer_lon)).kilometers
            if distance <= radius_km:
                filtered_offers.append(offer)
    return filtered_offers


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
    try:
        for url in urls:
            is_available = check_offer_availability(url[0])
            if not is_available:
                update_offer_availability(c, url[0], 0)
    except Exception as e:
        print(f"Error checking offer availability: {e}")
        return False
    return True


def get_offers_from_db(c, city, rooms, price_from, price_to, area_from, area_to, is_available):
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


def make_gui():

    class App(tk.Tk):
        def __init__(self, title, width, height):
            super().__init__()
            self.title(title)

            self.width = width
            self.height = height

            self.geometry(f"{width}x{height}")
            self.minsize(width, height)

            # widgets
            self.main = Main(self, self.on_submit_callback)
            self.menu = Menu(self, width, height, CITIES, self.main)

            self.mainloop()

        def on_submit_callback(self):
            return self.menu.on_submit()

    class Menu(tk.Frame):
        def __init__(self, parent, width, height, CITIES, main_instance):
            super().__init__(parent)
            #self.configure(bg='blue')

            self.place(x=0, y=0, relwidth=0.4, relheight=1)
            self.width = width
            self.height = height
            self.CITIES = CITIES
            self.submitted = False
            self.main = main_instance
            self.create_widgets()

        def setup_city_selection(self):
            # City selection
            city_label = ttk.Label(master=self, text="Choose or Enter City:",
                                   font="Calibri 24 bold")
            city_label.grid(row=1, column=0, columnspan=3, pady=(10, 0), padx=10, sticky='w')

            city_frame = ttk.Frame(master=self)
            city_frame.grid(row=2, column=0, columnspan=3, pady=(0, 5), padx=10, sticky='w')

            self.city_var = tk.StringVar()
            city_combobox = ttk.Combobox(master=city_frame, textvariable=self.city_var, values=self.CITIES,
                                         font="Calibri 24", justify='center')
            city_combobox.grid(row=0, column=1, padx=(50, 5), ipady=5)

            # Set default value to "Kraków"
            city_combobox.set("Kraków")



        def setup_room_selection(self):
            # Room selection
            room_label = ttk.Label(master=self, text="Choose Number of Rooms:",
                                   font=f"Calibri 24 bold")
            room_label.grid(row=3, column=0, columnspan=3, pady=(10, 0), padx=10, sticky='w')

            self.room_vars = {}  # Dictionary to store the BooleanVars for each room option
            room_frame = ttk.Frame(master=self)
            room_frame.grid(row=4, column=0, columnspan=3, pady=(0, 5), padx=10, sticky='w')

            # Define room options
            room_options = {'1 Room': 'one', '2 Rooms': 'two', '3 Rooms': 'three', '4+ Rooms': 'four+'}

            style = ttk.Style()
            style.configure("Custom.TCheckbutton", font=("Calibri", 18))

            # Create a Checkbutton for each room option
            for col, (text, room_value) in enumerate(room_options.items()):
                var = tk.BooleanVar()
                self.room_vars[room_value] = var
                room_check = ttk.Checkbutton(master=room_frame, text=text, variable=var, style="Custom.TCheckbutton")
                room_check.grid(row=0, column=col, sticky='nswe', padx=5, pady=5)

        def price_range(self):
            price_label = ttk.Label(master=self, text="Choose Price Range:", font="Calibri 24 bold")
            price_label.grid(row=5, column=0, columnspan=3, padx=10, sticky='w')  # Removed pady

            price_frame = ttk.Frame(master=self)
            price_frame.grid(row=6, column=0, columnspan=3, rowspan=2, padx=10, sticky='w')  # Removed pady

            self.price_from = tk.StringVar()
            self.price_to = tk.StringVar()

            # Entry fields for manual input
            price_label_from = ttk.Label(master=price_frame, text="From:", font="Calibri 18")
            price_label_from.grid(row=0, column=0, padx=(5, 5))
            price_from_entry = ttk.Entry(master=price_frame, textvariable=self.price_from, font="Calibri 18",
                                         justify='center')
            price_from_entry.grid(row=0, column=1, padx=(5, 0), ipady=5)

            price_label_to = ttk.Label(master=price_frame, text="To:", font="Calibri 18")
            price_label_to.grid(row=1, column=0, padx=(5, 5))
            price_to_entry = ttk.Entry(master=price_frame, textvariable=self.price_to, font="Calibri 18",
                                       justify='center')
            price_to_entry.grid(row=1, column=1, padx=(5, 0), ipady=5)

            # Frame for the sliders
            slider_frame = ttk.Frame(master=self)
            slider_frame.grid(row=8, column=0, columnspan=3, padx=10, sticky='w')  # Removed pady

            # Price From slider
            self.price_from_slider = tk.Scale(master=slider_frame, from_=0, to=10000, orient='horizontal', length=200,
                                              command=self.update_price_from)
            self.price_from_slider.grid(row=0, column=0, padx=(5, 10))

            # Price To slider
            self.price_to_slider = tk.Scale(master=slider_frame, from_=0, to=10000, orient='horizontal', length=200,
                                            command=self.update_price_to)
            self.price_to_slider.grid(row=0, column=1, padx=(10, 5))

        def update_price_from(self, value):
            self.price_from.set(value)

        def update_price_to(self, value):
            self.price_to.set(value)

        def area_range(self):
            area_label = ttk.Label(master=self, text="Choose Area Range:", font="Calibri 24 bold")
            area_label.grid(row=9, column=0, columnspan=3, padx=10, sticky='w')  # Removed pady

            area_frame = ttk.Frame(master=self)
            area_frame.grid(row=10, column=0, columnspan=3, rowspan=2, padx=10, sticky='w')  # Removed pady

            self.area_from = tk.StringVar()
            self.area_to = tk.StringVar()

            # Entry fields for manual input
            area_label_from = ttk.Label(master=area_frame, text="From:", font="Calibri 18")
            area_label_from.grid(row=0, column=0, padx=(5, 5))
            area_from_entry = ttk.Entry(master=area_frame, textvariable=self.area_from, font="Calibri 18",
                                         justify='center')
            area_from_entry.grid(row=0, column=1, padx=(5, 0), ipady=5)

            area_label_to = ttk.Label(master=area_frame, text="To:", font="Calibri 18")
            area_label_to.grid(row=1, column=0, padx=(5, 5))
            area_to_entry = ttk.Entry(master=area_frame, textvariable=self.area_to, font="Calibri 18",
                                       justify='center')
            area_to_entry.grid(row=1, column=1, padx=(5, 0), ipady=5)

            # Frame for the sliders
            slider_frame = ttk.Frame(master=self)
            slider_frame.grid(row=12, column=0, columnspan=3, padx=10, sticky='w')  # Removed pady

            # Price From slider
            self.price_from_slider = tk.Scale(master=slider_frame, from_=0, to=150, orient='horizontal', length=200,
                                              command=self.update_area_from)
            self.price_from_slider.grid(row=0, column=0, padx=(5, 10))

            # Price To slider
            self.price_to_slider = tk.Scale(master=slider_frame, from_=0, to=150, orient='horizontal', length=200,
                                            command=self.update_area_to)
            self.price_to_slider.grid(row=0, column=1, padx=(10, 5))

        def update_area_from(self, value):
            self.area_from.set(value)

        def update_area_to(self, value):
            self.area_to.set(value)

        def setup_furniture_selection(self):
            # Frame for the checkbox
            furniture_frame = ttk.Frame(master=self)
            furniture_frame.grid(row=13, column=0, columnspan=3, pady=(0, 5), padx=10, sticky='w')

            # Define a BooleanVar to track the state of the checkbox
            self.is_furnished = tk.BooleanVar(value=False)

            # Create a Checkbutton
            furniture_checkbutton = ttk.Checkbutton(master=furniture_frame, text="Furnished?",
                                                    variable=self.is_furnished, style="Custom.TCheckbutton")
            furniture_checkbutton.grid(row=0, column=0, sticky='w', padx=5, pady=5)

            # Customize Checkbutton style (optional)
            style = ttk.Style()
            style.configure("Custom.TCheckbutton", font=("Calibri", 18))

        def is_apartment_furnished(self):
            # This method can be used to check the state of the checkbox
            return self.is_furnished.get()


        def on_room_submit(self):
            selected_rooms = [key for key, var in self.room_vars.items() if var.get()]
            print(f"Selected room options: {selected_rooms}")

        def check_if_ready(self):
            # Check if all required fields are filled
            if not self.city_var.get():
                messagebox.showwarning("Warning", "Please select or enter a city.")
                return False
            if not self.price_from.get() or not self.price_to.get():
                messagebox.showwarning("Warning", "Please select a price range.")
                return False
            if not self.area_from.get() or not self.area_to.get():
                messagebox.showwarning("Warning", "Please select an area range.")
                return False
            if not any(self.room_vars.values()):
                messagebox.showwarning("Warning", "Please select the number of rooms.")
                return False
            if not self.submitted:
                messagebox.showwarning("Warning", "Please submit your search criteria first.")
                return False
            return True

        def on_submit(self):

            self.submitted = True
            city = self.city_var.get()

            if city in CITY_REPLACEMENTS:
                city = CITY_REPLACEMENTS[city]

            if city != "Kraków":
                tk.messagebox.showwarning("City Selection", "Only Kraków is supported. Please select or enter Kraków.")
                return

            if not city:
                messagebox.showerror("Input Error", "Please select or enter a city.")
                return

            # Get selected room options
            selected_rooms = [room for room, var in self.room_vars.items() if var.get()]
            if not selected_rooms:
                messagebox.showerror("Input Error", "Please select at least one room option.")
                return

            # Get price range
            try:
                price_from = int(self.price_from.get()) if self.price_from.get() else 0
                price_to = int(self.price_to.get()) if self.price_to.get() else 10000
            except ValueError:
                messagebox.showerror("Input Error", "Please enter valid numbers for price range.")
                return

            # Get area range
            try:
                area_from = int(self.area_from.get()) if self.area_from.get() else 0
                area_to = int(self.area_to.get()) if self.area_to.get() else 150
            except ValueError:
                messagebox.showerror("Input Error", "Please enter valid numbers for area range.")
                return

            # Get furniture status
            furniture = "yes" if self.is_furnished.get() else "no"

            furniture_text = "Furnished" if furniture else "Not furnished"
            selected_rooms_str = ", ".join([room.replace('_', ' ') for room in selected_rooms])

            result_text = f"City: {city}, Rooms: {selected_rooms_str}, Price: {price_from}-{price_to}, Area: {area_from}-{area_to}, {furniture_text}"
            result_label = ttk.Label(self, text=result_text, wraplength=self.width * 0.4, font="Calibri 15")
            result_label.grid(row=15, column=0, columnspan=3, padx=10, pady=(5, 5), sticky='w')

            return city, selected_rooms, price_from, price_to, furniture, area_from, area_to

        def search_existing_offers(self):
            if self.check_if_ready():
                pass
            else:
                messagebox.showwarning("Warning", "Please submit your selections before searching for new offers.")

        def setup_menu_buttons(self):
            menu_button1 = tk.Button(self, wraplength=100, justify='center', text="Search for new offers", bg='blue',
                                     fg='white', command=self.main.process_search)
            menu_button2 = tk.Button(self, wraplength=100, justify='center', text="Search through offers in database",
                                     bg='blue', fg='white', command=self.main.process_search_through_db)
            menu_button3 = tk.Button(self, wraplength=100, justify='center', text="Update offers availability",
                                     bg='blue', fg='white', command=self.main.check_availability)
            menu_button1.grid(row=0, column=0, sticky='nswe', padx=5, pady=5)
            menu_button2.grid(row=0, column=1, sticky='nswe', padx=5, pady=5)
            menu_button3.grid(row=0, column=2, sticky='nswe', padx=5, pady=5)



        def create_widgets(self):
            # Create the grid
            self.columnconfigure((0,1,2), weight=1, uniform='a', minsize=100)
            self.rowconfigure(tuple(range(1,16)), weight=1, uniform='a')

            # Create the buttons
            self.setup_menu_buttons()

            # City selection
            self.setup_city_selection()

            # Room selection
            self.setup_room_selection()

            # Price range
            self.price_range()

            # Area range
            self.area_range()

            # Furnished selection
            self.setup_furniture_selection()

            # Submit button
            submit_button = tk.Button(self, text="Submit", font="Calibri 24 bold", bg='green', fg='white',
                                        command=self.on_submit)
            submit_button.grid(row=14, column=0, columnspan=3, padx=10, pady=(10, 2), sticky='nswe')

            self.submitted = False


    class Main(ttk.Frame):
        def __init__(self, parent, on_submit_callback):
            super().__init__(parent)
            self.on_submit_callback = on_submit_callback
            #ttk.Label(self, background='red').pack(expand=True, fill='both')
            self.place(relx=0.4, rely=0, relwidth=0.6, relheight=1)
            self.create_widgets()

        def create_widgets(self):
            # Add a label at the top for the title or instructions
            ttk.Label(self, text="OLX Apartment Offers", font="Calibri 18 bold").pack(side="top", fill="x", pady=10)

            # Create a frame to hold the text widget and scrollbar
            text_frame = ttk.Frame(self)
            text_frame.place(relx=0, rely=0.1, relwidth=1, relheight=0.85)  # Adjust the placement

            # Create a Text widget to display offers
            self.result_text = tk.Text(text_frame, wrap="word", font="Calibri 14", cursor="arrow")
            self.result_text.place(relx=0, rely=0, relwidth=0.97, relheight=1)  # Adjust the placement

            # Create a scrollbar
            scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.result_text.yview)
            scrollbar.place(relx=0.97, rely=0, relwidth=0.03, relheight=1)  # Adjust placement of scrollbar
            self.result_text.configure(yscrollcommand=scrollbar.set)


        def display_offers(self, offers):
            # Clear the Text widget
            self.result_text.delete(1.0, tk.END)

            if offers:
                offers_text = ""
                for offer in offers:
                    offer_text = (f"Price: {offer[2]} PLN\n"
                                  f"Area: {offer[3]} sqm\nRooms: {offer[4]}\n"
                                  f"Location: {offer[5]}, {offer[7]}\n"
                                  f"Link: {offer[8]}\n\n"
                                  f"{'-' * 50}\n\n")
                    offers_text += offer_text

                    # Insert offer text
                    self.result_text.insert(tk.END, offer_text)

                    # Get the start and end index of the link
                    start_index = self.result_text.search(offer[8], "1.0", tk.END)
                    end_index = f"{start_index}+{len(offer[8])}c"

                    # Add a tag to the link
                    self.result_text.tag_add("link", start_index, end_index)
                    self.result_text.tag_config("link", foreground="blue", underline=True)

                    # Bind the click event to the link
                    self.result_text.tag_bind("link", "<Button-1>", lambda e, url=offer[8]: self.open_link(url))

            else:
                self.result_text.insert(tk.END, "No offers found.")

        def open_link(self, url):
            webbrowser.open(url)

        def get_offer_data(self, hrefs, city, patterns, cursor, progress_bar):
            new_offers = []
            total_offers_scraped = 0  # Track total offers processed

            for href in hrefs:
                if url_exists(cursor, href):
                    continue

                # Extract data for each offer
                extracted_data = get_data([href], city, patterns)

                if extracted_data is not None:
                    if extracted_data[6] and extracted_data[7] is not None:
                        insert_data(cursor, *extracted_data,
                                    *get_street_coordinates(cursor, extracted_data[6], extracted_data[7]))
                    else:
                        insert_data(cursor, *extracted_data, None, None)

                    # Add the offer to new_offers list
                    new_offers.append(extracted_data)

                # Update the progress bar for each processed offer
                total_offers_scraped += 1
                progress_bar["value"] = total_offers_scraped
                progress_bar.update_idletasks()  # Ensure the progress bar updates immediately

            progress_bar["value"] = len(hrefs)
            progress_bar.update_idletasks()  # Update the UI one last time

            # Once all offers are processed, display them
            self.display_offers(new_offers)

        def process_search(self):
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, "Searching for offers, please wait...\n")
            self.result_text.update_idletasks()  # Ensure the message is displayed immediately

            page_limit = simpledialog.askfloat("Page Limit",
                                                 "How many pages would you like to search through? (Min: 0.1 - Max: 5)",
                                                 minvalue=0.1, maxvalue=5)

            if not page_limit:
                self.result_text.insert(tk.END, "No page limit provided, cancelling search.\n")
                return

            # Create a popup window with a progress bar
            progress_popup = tk.Toplevel(self)
            progress_popup.title("Scraping Progress")
            progress_popup.geometry("300x100")

            # Add a progress bar to the popup window
            progress_label = ttk.Label(progress_popup, text="Scraping offers...")
            progress_label.pack(pady=10)
            progress_bar = ttk.Progressbar(progress_popup, orient="horizontal", length=250, mode="determinate")
            progress_bar.pack(pady=10)

            # Call on_submit() to gather search data
            search_data = self.on_submit_callback()
            city, rooms, price_from, price_to, furniture, area_from, area_to = search_data

            # Apply CITY_REPLACEMENTS to adjust city name
            for key, value in CITY_REPLACEMENTS.items():
                if city in value:
                    city = key
                    break

            # Construct the rooms URL part
            rooms_url = '&'
            for i, room in enumerate(rooms):
                rooms_url += f'search%5Bfilter_enum_rooms%5D%5B{i}%5D={room.strip()}'
                if i < len(rooms) - 1:
                    rooms_url += '&'

            page_limit2 = int(page_limit)
            if page_limit < 1:
                page_limit2 = 1
            page_number = 1

            hrefs = []

            while page_number <= page_limit2:
                try:
                    # Scrape offers from the current page
                    new_hrefs = scrape_olx("https://www.olx.pl/nieruchomosci/mieszkania/wynajem/", city, price_from,
                                           price_to,
                                           rooms_url, furniture, area_from, area_to, page_number)

                    hrefs += new_hrefs
                    page_number += 1


                    time.sleep(1)

                except requests.RequestException as e:
                    self.result_text.insert(tk.END, f"Request error: {e}")
                    progress_popup.destroy()
                    return

            if page_limit < 1:
                hrefs = hrefs[:int(page_limit * len(hrefs))]
            print(len(hrefs))
            progress_bar["maximum"] = len(hrefs)

            progress_bar.update_idletasks()


            # Load search patterns
            patterns = load_patterns_from_file("patterns.txt")

            conn = None
            try:
                conn = sqlite3.connect('olx_offers.db')
                c = conn.cursor()
                create_database(c)
                clean_database(c)

                self.get_offer_data(hrefs, city, patterns, c, progress_bar)

                conn.commit()

            except sqlite3.Error as e:
                self.result_text.insert(tk.END, f"SQLite error: {e}")
            except Exception as e:
                self.result_text.insert(tk.END, f"An error occurred: {e}")
            finally:
                if conn:
                    conn.close()
                progress_popup.destroy()


        def process_search_through_db(self):

            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, "Checking availability of offers, please wait...\n")
            self.result_text.update_idletasks()

            # Call on_submit() to gather search data
            search_data = self.on_submit_callback()
            city, rooms, price_from, price_to, furniture, area_from, area_to = search_data

            # Apply CITY_REPLACEMENTS to adjust city name
            for key, value in CITY_REPLACEMENTS.items():
                if city in key:
                    city = value
                    break

            try:
                conn = sqlite3.connect('olx_offers.db')
                c = conn.cursor()
                create_database(c)
                clean_database(c)

                offers = get_offers_from_db(c, city, rooms, price_from, price_to, area_from, area_to, 1)

                if self.circle_center and self.circle_radius:
                    offers = filter_offers_within_circle(offers, self.circle_center[0], self.circle_center[1],
                                                         self.circle_radius)

                streets_with_prefixes_and_hrefs = [(offer[6], offer[7], offer[8]) for offer in offers if
                                                   offer[7] is not None]

                # Mark the filtered streets on the map
                mark_streets(c, streets_with_prefixes_and_hrefs)

                conn.close()
                self.display_offers(offers)
            except sqlite3.Error as e:
                self.result_text.insert(tk.END, f"SQLite error: {e}")
            except Exception as e:
                self.result_text.insert(tk.END, f"An error occurred: {e}")
            finally:
                if conn:
                    conn.close()
                else:
                    pass

        def check_availability(self):
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, "Checking availability of offers, please wait...\n")
            self.result_text.update_idletasks()

            try:
                conn = sqlite3.connect('olx_offers.db')
                c = conn.cursor()
                create_database(c)
                clean_database(c)

                check_data(c)

                self.result_text.insert(tk.END, f"Offers availability updated successfully.\n")
            except sqlite3.Error as e:
                self.result_text.insert(tk.END, f"SQLite error: {e}")
            except Exception as e:
                self.result_text.insert(tk.END, f"An error occurred: {e}")
            finally:
                if conn:
                    conn.close()
                else:
                    pass

    App('OLX Apartments Scraper', 1200, 800)


if __name__ == '__main__':
    locale.setlocale(locale.LC_TIME, 'pl_PL.UTF-8')

    make_gui()