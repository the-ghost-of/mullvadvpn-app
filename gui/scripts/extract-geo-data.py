#!/usr/bin/env python3
"""
This module forms a geo json of highly populated cities in the world
"""

import os
from os import path
import json
import urllib.request
from subprocess import Popen, PIPE
from polib import POFile, POEntry
import colorful as c
from terminaltables import AsciiTable

import fiona
# import order is important, see https://github.com/Toblerity/Shapely/issues/553
from shapely.geometry import shape, mapping

SCRIPT_DIR = path.dirname(path.realpath(__file__))

# The directory with the existing localizations content
LOCALE_DIR = path.normpath(path.join(SCRIPT_DIR, "../locales"))

# The output directory for the generated content
OUT_DIR = path.join(SCRIPT_DIR, "out")

# the directory with the generated localizations content
LOCALE_OUT_DIR = path.join(OUT_DIR, "locales")

# Relay locations gettext catalogue template filename (.pot)
RELAY_LOCATIONS_POT_FILENAME = "relay-locations.pot"

# Relay locations gettext catalogue filename (.po)
RELAY_LOCATIONS_PO_FILENAME = "relay-locations.po"

# Custom locale mapping between the identifiers in the app and Natural Earth datasets
LOCALE_MAPPING = {
  # "zh" in Natural Earth Data referes to simplified chinese
  "zh-CN": "zh"
}


def extract_geometry():
  input_path = get_shape_path("ne_50m_admin_0_countries")
  output_path = path.join(OUT_DIR, "geometry.json")

  features = []
  with fiona.open(input_path) as source:
    for feat in source:
      del feat["properties"]
      geometry = feat["geometry"]
      feat["bbox"] = shape(geometry).bounds
      features.append(feat)

  my_layer = {
    "type": "FeatureCollection",
    "features": features
  }

  with Popen(
      ['geo2topo', '-q', '5e3', 'geometry=-', '-o', output_path],
      stdin=PIPE, stdout=PIPE, stderr=PIPE
    ) as subproc:
    errors = subproc.communicate(input=json.dumps(my_layer).encode())[1]
    if subproc.returncode == 0:
      print(c.green(f"Extracted data to {output_path}"))
    else:
      print(
          c.red(
              f"geo2topo exited with {subproc.returncode}. {errors.decode().strip()}"
          ))


def extract_provinces_and_states_lines():
  input_path = get_shape_path("ne_50m_admin_1_states_provinces_lines")
  output_path = path.join(OUT_DIR, "states-provinces-lines.json")

  features = []
  with fiona.open(input_path) as source:
    for feat in source:
      del feat["properties"]
      geometry = feat["geometry"]
      feat["bbox"] = shape(geometry).bounds
      features.append(feat)

  my_layer = {
    "type": "FeatureCollection",
    "features": features
  }

  with Popen(
      ['geo2topo', '-q', '5e3', 'geometry=-', '-o', output_path],
      stdin=PIPE, stdout=PIPE, stderr=PIPE
    ) as subproc:
    errors = subproc.communicate(input=json.dumps(my_layer).encode())[1]
    if subproc.returncode == 0:
      print(c.green(f"Extracted data to {output_path}"))
    else:
      print(
          c.red(
              f"geo2topo exited with {subproc.returncode}. {errors.decode().strip()}"
          ))


def sort_pofile_entries(pofile):
  pofile.sort(key=lambda o: o.msgid_with_context)


def extract_relay_translations():
  try:
    response = request_relays()
  except Exception as e:
    print(c.red(f"Failed to fetch the relays list: {e}"))
    raise

  locations = response.get("locations")
  countries = structure_locations(locations)

  extract_relay_locations_pot(countries)
  translate_relay_locations(countries)


def structure_locations(locations):
  countries = {}

  for location_key in locations:
    location = locations.get(location_key)
    country_name = location.get("country")
    city_name = location.get("city")

    if "-" not in location_key:
      print(f"Location key incorrectly formatted: {location_key}")
      continue

    country_code, city_code = location_key.split("-")

    if country_name is None:
      print(f"Country name missing for {location_key}")
      continue

    if city_name is None:
      print(f"City name missing for {location_key}")
      continue

    if country_code not in countries:
      countries[country_code] = {"name": country_name, "cities": {}}

    country = countries[country_code]
    if location_key != "se-bet":
      cities = country["cities"]
      if city_code not in cities:
        cities[city_code] = city_name
      else:
        print(f"There are multiple entries for {city_name} in {country_name}")

  return countries


def extract_relay_locations_pot(countries):
  pot = POFile(encoding='utf-8', check_for_duplicates=True)
  pot.metadata = {"Content-Type": "text/plain; charset=utf-8"}
  output_path = path.join(LOCALE_OUT_DIR, RELAY_LOCATIONS_POT_FILENAME)

  print(f"Generating {output_path}")

  for country_code in countries:
    country = countries[country_code]
    entry = POEntry(
      msgid=country["name"],
      msgstr="",
      comment=country_code.upper()
    )
    pot.append(entry)

    cities = country["cities"]
    for city_code in cities:
      entry = POEntry(
          msgid=cities[city_code],
          msgstr="",
          comment=f"{country_code.upper()} {city_code.upper()}",
      )

      try:
        pot.append(entry)
      except ValueError as err:
        print(c.orange(f"Cannot add an entry: {err}"))

  pot.save(output_path)


def prepare_stats_table_column(item):
  (locale, hits, misses) = item
  total = hits + misses
  hits_ratio = round(float(hits) / total * 100, 2) if total > 0 else 0

  misses_column = c.orange(str(misses)) if misses > 0 else c.green(str(misses))
  hits_column = c.green(str(hits))
  ratio_column = (c.green(f"{str(hits_ratio)}%")
                  if hits_ratio >= 80 else c.orange(str(hits_ratio)))
  total_column = str(total)

  return (locale, hits_column, misses_column, ratio_column, total_column)

def print_stats_table(title, data):
  header = ("Locale", "Hits", "Misses", "% translated", "Total")
  color_data = list(map(prepare_stats_table_column, data))

  table = AsciiTable([header] + color_data)
  table.title = title

  for i in range(1, 5):
    table.justify_columns[i] = 'center'

  print("")
  print(table.table)
  print("")


def translate_relay_locations(countries):
  """
  A helper function to generate the relay-locations.po with automatic translations for each
  corresponding locale.

  The `countries` argument is an array that's contained within the "countries" key of the
  relay location list.
  """

  country_translator = CountryTranslator()
  city_translator = CityTranslator()
  stats = []

  for locale in os.listdir(LOCALE_DIR):
    locale_dir = path.join(LOCALE_DIR, locale)
    if path.isdir(locale_dir):
      print(f"Generating {path.join(locale, RELAY_LOCATIONS_PO_FILENAME)}")
      (hits, misses) = translate_single_relay_locations(country_translator, city_translator, countries, locale)
      stats.append((locale, hits, misses))

  print_stats_table("Relay location translations", stats)


def translate_single_relay_locations(country_translator, city_translator, countries, locale):
  """
  A helper function to generate the relay-locations.po for the given locale.

  The `countries` argument is an array value that's contained within the "countries" key of the
  relay location list.
  """

  po = POFile(encoding='utf-8', check_for_duplicates=True)
  po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
  locale_out_dir = path.join(LOCALE_OUT_DIR, locale)
  output_path = path.join(locale_out_dir, RELAY_LOCATIONS_PO_FILENAME)

  hits = 0
  misses = 0

  if not path.exists(locale_out_dir):
    os.makedirs(locale_out_dir)

  for country_code in countries:
    country = countries[country_code]
    country_name = country["name"]

    translated_country_name = country_translator.translate(locale, country_code)
    # Default to empty string if no translation was found
    if translated_country_name is not None:
      hits += 1
    else:
      translated_country_name = ""
      misses += 1

    # translate country
    entry = POEntry(
      msgid=country_name,
      msgstr=translated_country_name,
      comment=country_code.upper()
    )
    po.append(entry)

    # translate cities
    cities = country["cities"]
    for city_code in cities:
      city_name = cities[city_code]

      # Make sure to append the US state back to the translated name of the city
      if country_code == "us":
        split = city_name.rsplit(",", 2)
        translated_name = city_translator.translate(locale, split[0].strip())

        if translated_name is not None and len(split) > 1:
          translated_name = f"{translated_name}, {split[1].strip()}"
      else:
        translated_name = city_translator.translate(locale, city_name)

      # Default to empty string if no translation was found
      found_translation = translated_name is not None
      if found_translation:
        hits += 1
      else:
        translated_name = ""
        misses += 1

      entry = POEntry(
          msgid=city_name,
          msgstr=translated_name,
          comment=f"{country_code.upper()} {city_code.upper()}",
      )

      try:
        po.append(entry)
      except ValueError as err:
        print(c.orange(f"Cannot add an entry: {err}"))

  po.save(output_path)

  return (hits, misses)


### HELPERS ###

class CountryTranslator:
  """
  This class provides facilities for translating countries
  """

  def __init__(self):
    self.dataset = self.__build_index()

  def translate(self, locale, iso_a2):
    """
    Lookup the countries dataset for the country matching by ISO A2 code

    When there is a match, the function looks for the translation using the given locale or using
    the language component of it.

    Returns None when either there is no match or there is no translation for the matched city.
    """
    props = self.dataset.get(iso_a2.upper())

    if props is not None:
      name_key = f"name_{map_locale(locale)}"
      return props.get(name_key)

    return None


  def __build_index(self):
    """
    Private helper to build the index for the geo dataset, that can be used to speed up the
    translations lookup.
    """
    shape_path = get_shape_path("ne_50m_admin_0_countries")
    dataset = {}

    # build a hash map of the entire datasource in memory
    with fiona.open(shape_path, "r") as source:
      for feat in source:
        props = lower_dict_keys(feat["properties"])

        iso_a2 = props.get("iso_a2")
        if iso_a2 is not None:
          dataset[iso_a2.upper()] = props

    return dataset


class CityTranslator:
  """
  This class provides facilities for translating places from English.
  """

  def __init__(self):
    self.dataset = self.__build_index()

  def translate(self, locale, english_name):
    """
    Lookup the populated places dataset for the city matching by name, par name or
    name representation in ASCII.

    When there is a match, the function looks for the translation using the given locale or using
    the language component of it.

    Returns None when either there is no match or there is no translation for the matched city.
    """
    props = self.dataset.get(english_name)

    if props is not None:
      name_key = f"name_{map_locale(locale)}"
      return props.get(name_key)

    return None

  def __build_index(self):
    """
    Private helper to build the index for the geo dataset, that can be used to speed up the
    translations lookup.
    """
    shape_path = get_shape_path("ne_10m_populated_places")
    dataset = {}

    # build a hash map of the entire datasource in memory
    with fiona.open(shape_path, "r") as source:
      for feat in source:
        props = lower_dict_keys(feat["properties"])

        name = props.get("name")

        # namepar works for "Wien"
        namepar = props.get("namepar")

        # use nameascii to match "Sao Paolo"
        nameascii = props.get("nameascii")

        if name is not None:
          dataset[name] = props

        if namepar is not None:
          dataset[namepar] = props

        if nameascii is not None:
          dataset[nameascii] = props

    return dataset


def get_shape_path(dataset_name):
  return path.join(SCRIPT_DIR, dataset_name, f"{dataset_name}.shp")


def lower_dict_keys(input_dict):
  return {k.lower(): v for k, v in input_dict.items()}


def convert_locale_ident(locale_ident):
  """
  Return the locale identifie converting dashes to underscores.

  Example: en-US becomes en_US
  """
  return locale_ident.replace("-", "_")


def map_locale(locale_ident):
  """
  Map the locale in Natural Earth Data with the locale in the app and Crowdin
  """
  if locale_ident in LOCALE_MAPPING:
    locale_override = LOCALE_MAPPING[locale_ident]
  else:
    locale_override = locale_ident

  return convert_locale_ident(locale_override)


def request_relays():
  request = urllib.request.Request("https://api.mullvad.net/app/v1/relays")
  with urllib.request.urlopen(request) as connection:
    return json.load(connection)


# Program main()

def main():
  # ensure output path exists
  if not path.exists(OUT_DIR):
    os.makedirs(OUT_DIR)

  # ensure locales output path exists
  if not path.exists(LOCALE_OUT_DIR):
    os.makedirs(LOCALE_OUT_DIR)

  # extract geo data
  extract_geometry()
  extract_provinces_and_states_lines()

  # extract translations
  extract_relay_translations()

main()
