"""Script for scraping baby name info from behindthename.com, and baby name frequencies in the USA from the Social Security Administration website."""

from bs4 import BeautifulSoup, Tag
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
import os
import re
import requests
import string
from tqdm import tqdm
from typing import Any, Dict, Tuple

AnyDict = Dict[Any, Any]
JSONDict = Dict[str, Any]


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url)
    return BeautifulSoup(response.text, 'html.parser')

def normalize_name(name: str) -> str:
    return re.sub(r'\(?\d+\)?$', '', name).strip()


class BehindTheName:
    """Class for scraping name info from behindthename.com."""
    def __init__(self, get_ratings: bool = False) -> None:
        self.get_ratings = get_ratings
        self.name_info: JSONDict = {'first' : defaultdict(list), 'last' : defaultdict(list)}
    def save(self, path: str) -> None:
        d = {'has_ratings' : self.get_ratings, 'names' : self.name_info}
        with open(path, 'w') as f:
            json.dump(d, f, ensure_ascii = False, indent = 1)
    @classmethod
    def load(cls, path: str) -> 'BehindTheName':
        with open(path) as f:
            d = json.load(f)
        btn = cls(d['has_ratings'])
        btn.name_info = d['names']
        return btn
    @staticmethod
    def process_name_entry(entry: Tag) -> Tuple[str, JSONDict]:
        name = entry.find('span', attrs = {'class' : 'listname'}).text
        name = normalize_name(name)  # some entries have multiple versions
        gender = ''
        if entry.find('span', attrs = {'class' : 'masc'}):
            gender += 'M'
        if entry.find('span', attrs = {'class' : 'fem'}):
            gender += 'F'
        languages = [lang.text for lang in entry.find_all('a', attrs = {'class' : 'usg'})]
        # if entry.find(class_ = 'text-function'):
            # TODO: description is too long, need to navigate to its page
            # TODO: also get variants, diminutives, etc.
        description = ''.join(piece.text if hasattr(piece, 'text') else piece for piece in entry.find('br').next_siblings)
        related = [normalize_name(link.text) for link in entry.find_all(class_ = 'nl')]
        entry_data: JSONDict = {}
        if gender:
            entry_data['gender'] = gender
        entry_data.update({'languages' : languages, 'descr' : description})
        # print(f'{name}\nGender: {gender}\nLanguages: {str(languages)[1:-1]}\nDescription: {description}\n')
        if related:
            entry_data['related'] = related
        return (name, entry_data)
    def scrape_first_name_page(self, gender: str, pagenum: int) -> None:
        """Scrapes data from a single page."""
        names_url = os.path.join('https://www.behindthename.com/names/gender', gender)
        page_url = os.path.join(names_url, str(pagenum))
        soup = get_soup(page_url)
        entries = soup.find_all('div', attrs = {'class' : 'browsename'})
        for entry in entries:
            (name, entry_data) = self.process_name_entry(entry)
            if self.get_ratings:  # get the ratings
                rating_url = os.path.join('https://www.behindthename.com', entry.find('a').attrs['href'][1:], 'rating')
                try:
                    soup = get_soup(rating_url)
                    table = soup.find('table', attrs = {'cellspacing' : '10'})
                    if table:
                        ratings = dict()
                        for row in table.find_all('tr'):
                            cols = row.find_all('td')
                            attr = cols[0].text.strip()
                            percent = int(cols[1].text[:-1])
                            ratings[attr] = percent
                        entry_data['ratings'] = ratings
                        entry_data['num_raters'] = int(table.find_next_sibling().text.split()[-2])
                except (ConnectionError, TimeoutError):
                    continue
            if (entry_data not in self.name_info['first'][name]):
                self.name_info['first'][name].append(entry_data)
    def scrape_first_names(self) -> None:
        for gender in ['masculine', 'feminine', 'unisex']:
            print(f'Scraping {gender} names...')
            names_url = os.path.join('https://www.behindthename.com/names/gender', gender)
            soup = get_soup(names_url)
            page_href = os.path.join('^/names/gender', gender, '*')
            pagenums = [int(a.attrs.get('href').split('/')[-1]) for a in soup.find_all('a', href = re.compile(page_href))]
            maxpage = max(pagenums)
            for pagenum in tqdm(range(1, maxpage + 1)):
                self.scrape_first_name_page(gender, pagenum)
    @staticmethod
    def base_surname_url(submit: bool) -> str:
        return 'https://surnames.behindthename.com/submit/names/letter' if submit else 'https://surnames.behindthename.com/names/letter'
    def scrape_last_name_page(self, letter: str, pagenum: int, submit: bool) -> None:
        surnames_url = os.path.join(self.base_surname_url(submit), letter)
        page_url = os.path.join(surnames_url, str(pagenum))
        soup = get_soup(page_url)
        entries = soup.find_all('div', attrs = {'class' : 'browsename'})
        for entry in entries:
            (name, entry_data) = self.process_name_entry(entry)
            entry_data['submitted'] = submit
            descr = entry_data.get('descr')
            eds = self.name_info['last'][name]
            if (not any(descr == ed.get('descr') for ed in eds)):
                eds.append(entry_data)

    def scrape_last_names(self) -> None:
        for submit in [False, True]:
            if submit:
                print('Scraping user-submitted surnames...')
            else:
                print('Scraping surnames...')
            for letter in string.ascii_lowercase:
                print(letter)
                surnames_url = os.path.join(self.base_surname_url(submit), letter)
                soup = get_soup(surnames_url)
                page_href = os.path.join('^/submit/names/letter' if submit else '^/names/letter', letter, '*')
                pagenums = [int(a.attrs.get('href').split('/')[-1]) for a in soup.find_all('a', href = re.compile(page_href))]
                maxpage = max(pagenums) if pagenums else 1
                for pagenum in tqdm(range(1, maxpage + 1)):
                    self.scrape_last_name_page(letter, pagenum, submit)

class SSA:
    """Class for scraping name stats from the SSA website."""
    def __init__(self) -> None:
        self.name_stats: JSONDict = {}
    def scrape(self) -> None:
        main_url = 'https://www.ssa.gov/OACT/babynames/index.html'
        soup = get_soup(main_url)
        first_year = int(soup.find('p', text = re.compile(r'Any year after \d{4}')).text[-4:]) + 1
        this_year = datetime.now().year
        name_count_url = 'https://www.ssa.gov/cgi-bin/popularnames.cgi'
        stats = self.name_stats
        criteria = [('n', 'count'), ('p', 'prob')]
        for year in range(first_year, this_year):
            print(year)
            for (crit, crit_name) in criteria:
                response = requests.post(name_count_url, data = {'year' : year, 'top' : 1000, 'number' : crit})
                soup = BeautifulSoup(response.text, 'html.parser')
                table = soup.find('table', attrs = {'summary' : 'Popularity for top 1000'})
                rows = table.find_all('tr')
                for (i, row) in enumerate(rows[1:-1]):
                    cols = [col.text for col in row.find_all('td')]
                    assert (len(cols) == 5) and (int(cols[0]) == i + 1)
                    male_name = cols[1]
                    male_count = int(cols[2].replace(',', '')) if (crit == 'n') else round(float(cols[2][:-1]) / 100, 7)
                    female_name = cols[3]
                    female_count = int(cols[4].replace(',', '')) if (crit == 'n') else round(float(cols[4][:-1]) / 100, 7)
                    if (len(male_name) > 0):
                        entry = stats.setdefault(male_name, {}).setdefault('M', {})
                        entry.setdefault(crit_name, {})[year] = male_count
                        entry.setdefault('rank', {})[year] = i + 1
                    if (len(female_name) > 0):
                        entry = stats.setdefault(female_name, {}).setdefault('F', {})
                        entry.setdefault(crit_name, {})[year] = female_count
                        entry.setdefault('rank', {})[year] = i + 1

@dataclass
class NameDB:
    btn: BehindTheName = BehindTheName()
    def save(self, path: str) -> None:
        self.btn.save(path)
    @classmethod
    def load(cls, path: str) -> 'NameDB':
        btn = BehindTheName.load(path)
        return NameDB(btn)
    def merge_ssa(self, ssa: SSA) -> None:
        """Merges in stats from SSA."""
        for (name, d) in ssa.name_stats.items():
            for (gender, stats) in d.items():
                entries = self.btn.name_info['first'].setdefault(name, [])
                for entry in entries:
                    if (gender in entry['gender']):  # matched the entry
                        break
                else:  # create new entry
                    entry = {'gender' : gender}
                entry['ssa'] = stats
