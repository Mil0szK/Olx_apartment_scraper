import numpy as np
import pandas as pd


def clean_data():
    words_to_detect = ['Nr', 'Nr.', 'Brak', 'Tylko', 'Wszystkie']
    df = pd.read_csv('sample.csv')
    for i, row in df.iterrows():
        for word in words_to_detect:
            if word in str(row['Street']):
                index = row['Street'].find(word)
                row['Street'] = row['Street'][:index].strip()

    df = df.dropna()

    df = df.drop_duplicates(subset=['Street'], keep='first')

    df['Street'] = df['Street'].str.strip()
    df['District'] = df['District'].str.strip()

    df['Street'] = df['Street'].str.lower()
    df['District'] = df['District'].str.lower()


    df.to_csv('cleaned_sample.csv', index=False)


if __name__ == '__main__':
    clean_data()
