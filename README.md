# OLX Apartment Scraper

This is a simple web scraper that scrapes the OLX website for apartments in Kraków. The scraper is written in Python and
uses the BeautifulSoup library to scrape the website. The data is stored in SQLite database.
Program work as GUI application, with the ability to search for apartments by city, district, price, area, number of rooms and floor.
User in the GUI can search new offers from the website, search through the database, or update the availability of the offers.

## Setup

1. Clone the repository
2. Install the required dependencies with `pip install -r requirements.txt`.
3. Run the program with `python olx_scraping.py`.

## Usage
User chooses the parameters of the search and clicks the "Submit" button. Next, use preferred option from the menu
of the top of the window. Offers will be displayed in the result window.

## To Be Done
- Write tests
- Add more cities
- Create an analysis of the data