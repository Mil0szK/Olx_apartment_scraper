import PyPDF2
import csv

def pdf_to_text(pdf_path, output_txt):
    filter = ['OSIEDLE', 'ULICA', 'ALEJA', 'RONDO']
    tax_office = ['US', 'KR', 'NH', 'PD', 'PK', 'SM', 'ŚR']
    with open(pdf_path, 'rb') as pdf_file:
        reader = PyPDF2.PdfReader(pdf_file)
        with open(output_txt, 'w') as output:
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                text = page.extract_text()
                lines = text.split('\n')
                for line in lines:
                    words = line.split()
                    for i, word in enumerate(words):
                        if word in tax_office:
                            words[i] = ';'
                    line = ' '.join(words)
                    for word in filter:
                        if word in line:
                            start = line.find(word) + len(word)
                            end = line.find(';')
                            if start != -1 and end != -1:
                                extracted_street = line[start:end].strip()
                                extracted_district = line[end:].strip()
                                output.write(f"{extracted_street}{extracted_district}\n")


def txt_to_csv(txt_path, csv_path):
    with open(txt_path, 'r') as txt_file:
        with open(csv_path, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(['Street', 'District'])
            for line in txt_file:
                line = line.strip()
                if line:
                    if len(line.split(";")) >= 2:
                        street, district = line.split(";")
                        writer.writerow([street.strip(), district.strip()])



if __name__ == '__main__':
    pdf_to_text('zasieg_terytorialny.pdf', 'sample.txt')
    txt_to_csv('sample.txt', 'sample.csv')
