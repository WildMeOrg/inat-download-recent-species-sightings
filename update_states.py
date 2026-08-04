#!/usr/bin/env python3
"""
Update Encounter.locationID in CSV based on Encounter.verbatimLocality
Maps Brazilian municipalities and states to their correct state names
"""

import argparse
import csv
import os
import tempfile

# Mapping of localities to Brazilian states
# Based on the unique localities found in the CSV
LOCALITY_TO_STATE = {
    # Cities to States
    "Altamira, BR-PA, BR": "Pará",
    "Aquidauana, BR-MS, BR": "Mato Grosso do Sul",
    "Aruanã, BR-GO, BR": "Goiás",
    "Barão de Melgaço, BR-MT, BR": "Mato Grosso",
    "Canarana, BR-MT, BR": "Mato Grosso",
    "Corumbá, BR-MS, BR": "Mato Grosso do Sul",
    "Costa Marques, BR-RO, BR": "Rondônia",
    "Cáceres, BR-MT, BR": "Mato Grosso",
    "Feijó, BR-AC, BR": "Acre",
    "Marabá, BR-PA, BR": "Pará",
    "Maués, BR-AM, BR": "Amazonas",
    "Miranda, BR-MS, BR": "Mato Grosso do Sul",
    "Novo Airão, BR-AM, BR": "Amazonas",
    "Oriximiná, BR-PA, BR": "Pará",
    "Parauapebas, BR-PA, BR": "Pará",
    "Poconé, BR-MT, BR": "Mato Grosso",
    "Presidente Figueiredo, BR-AM, BR": "Amazonas",

    # States themselves (already state names)
    "Amapá, BR": "Amapá",
    "Amazonas, BR": "Amazonas",
    "Bahia, BR": "Bahia",
    "Goiás, BR": "Goiás",
    "Mato Grosso, BR": "Mato Grosso",
    "Mato Grosso do Sul, BR": "Mato Grosso do Sul",
    "Pará, BR": "Pará",
    "São Paulo, BR": "São Paulo",
    "Tocantins, BR": "Tocantins",

    # Just "Brazil" - leave as is
    "Brazil": "Brazil"
}

def update_csv(input_file, output_file):
    """Update the locationID column based on verbatimLocality"""

    rows_updated = 0
    rows_unchanged = 0

    with open(input_file, 'r', encoding='utf-8', newline='') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames

        rows = []
        for row in reader:
            locality = row['Encounter.verbatimLocality']
            current_location_id = row['Encounter.locationID']

            # Try to map the locality to a state
            if locality in LOCALITY_TO_STATE:
                new_location_id = LOCALITY_TO_STATE[locality]
                row['Encounter.locationID'] = new_location_id

                if new_location_id != current_location_id:
                    rows_updated += 1
                else:
                    rows_unchanged += 1
            else:
                # No mapping found, leave as "Brazil"
                rows_unchanged += 1
                print(f"No mapping for: {locality}")

            rows.append(row)

    # Write to a temporary file in the destination directory, then rename over
    # the target. Writing straight to output_file meant an interruption or a
    # full disk left the only copy of the bulk-import CSV truncated -- and the
    # shipped defaults had output_file == input_file.
    out_path = os.path.abspath(output_file)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(out_path) or '.', prefix='.update_states-', suffix='.csv'
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, out_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    print(f"\nUpdate complete!")
    print(f"Rows updated: {rows_updated}")
    print(f"Rows unchanged: {rows_unchanged}")
    print(f"Total rows: {rows_updated + rows_unchanged}")
    print(f"Output written to: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Map Encounter.verbatimLocality to a Brazilian state in Encounter.locationID."
    )
    parser.add_argument('input_file', help='CSV to read')
    parser.add_argument(
        '-o', '--output',
        help='CSV to write (default: alongside the input, with a .updated.csv suffix). '
             'Pass the input path explicitly to edit in place.'
    )
    args = parser.parse_args()

    output = args.output or args.input_file.replace('.csv', '') + '.updated.csv'
    update_csv(args.input_file, output)
