from pypdf import PdfReader
from pathlib import Path
import re
import pandas as pd
import argparse
from sys import stderr


def parse_ing_kontoauszug(file: Path) -> pd.DataFrame:
    """
    Parses a given Kontoauszug PDF file and returns its contents as a pandas DataFrame.

    Every booking spans several lines in the PDF: the booking line (date, description,
    amount), the valuta line (valuta date and the start of the Verwendungszweck) and
    optional continuation lines (rest of the Verwendungszweck, Mandat, Referenz, ...).

    Parameters:
        file (Path): The path to the kontoauszug PDF file.

    Returns:
        pd.DataFrame: A DataFrame containing the parsed data from the kontoauszug PDF file. The DataFrame has five columns: 'date' (datetime), 'valuta' (datetime), 'description' (str), 'purpose' (str) and 'amount' (float).
    """
    reader = PdfReader(file)
    results = {"date": [], "valuta": [], "description": [], "purpose": [], "amount": []}
    date = r"(?:0[1-9]|[12][0-9]|3[01])[.](?:0[1-9]|1[012])[.](?:19|20)[0-9]{2}"
    # a real amount always has two decimals; pypdf sometimes appends a stray digit
    booking_regex = re.compile(
        rf"^({date}) (.*?) ?(-?(?:\d{{1,3}}(?:\.\d{{3}})*|\d+),\d{{2}})\d?$"
    )
    valuta_regex = re.compile(rf"^({date}) ?(.*)$")
    # lines that end the booking table of a page
    end_regex = re.compile(r"^(?:[\w-]+ Nummer \d+|Neuer Saldo .*|[0-9A-Z]+_T)$")
    header_lines = {"Buchung Buchung / Verwendungszweck Betrag (EUR)", "Valuta"}

    purpose = None
    expect_valuta = False

    def finish_purpose():
        if purpose is not None:
            results["purpose"].append(" ".join(purpose))

    for page in reader.pages:
        content = page.extract_text(0)

        for line in content.split("\n"):
            line = line.strip()
            if expect_valuta:
                expect_valuta = False
                valuta = valuta_regex.match(line)
                if valuta is not None:
                    results["valuta"].append(valuta.group(1))
                    purpose = [valuta.group(2)] if valuta.group(2) else []
                    continue
                print(f"{file.name}: missing valuta line before {line!r}", file=stderr)
                results["valuta"].append(results["date"][-1])
                purpose = []

            booking = booking_regex.match(line)
            if booking is not None:
                finish_purpose()
                results["date"].append(booking.group(1))
                results["description"].append(booking.group(2))
                results["amount"].append(
                    float(booking.group(3).replace(".", "").replace(",", "."))
                )
                purpose = None
                expect_valuta = True
            elif purpose is not None:
                if end_regex.match(line):
                    finish_purpose()
                    purpose = None
                elif line and line not in header_lines:
                    purpose.append(line)

    if expect_valuta:
        results["valuta"].append(results["date"][-1])
        purpose = []
    finish_purpose()

    data = pd.DataFrame(results)
    data["date"] = pd.to_datetime(data["date"], format="%d.%m.%Y")
    data["valuta"] = pd.to_datetime(data["valuta"], format="%d.%m.%Y")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "path",
        metavar="INPUT",
        type=str,
        help="Can be a file or a directory with the ING PDF files",
    )
    # -a, --account
    parser.add_argument(
        "-a",
        "--account",
        type=str,
        required=False,
        default="giro",
        help="Account type to parse if directory is specified e.g. Giro, Extra (Default: Giro)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        required=False,
        default="ing_kontoauszug.csv",
        help="Output file (Default: ing_kontoauszug.csv)",
    )
    args = parser.parse_args()

    path = Path(args.path)

    if path.is_file() and path.suffix == ".pdf":
        df = parse_ing_kontoauszug(Path(args.path))
    elif path.is_dir():
        df = []
        for file in path.glob("*.pdf"):
            if ("kontoauszug" in file.name.lower()) and (
                args.account.lower() in file.name.lower()
            ):
                df.append(parse_ing_kontoauszug(file))
        df = pd.concat(df)
    else:
        print(f"Invalid input: {path}", file=stderr)
        exit(1)

    df = df.sort_values("date", ascending=False)
    df.to_csv(args.output, index=False)
