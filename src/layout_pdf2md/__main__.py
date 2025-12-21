import argparse
from layout_pdf2md import pdf2md


def main():
    parser = argparse.ArgumentParser(description="PDF preprocessing tool")
    parser.add_argument("input", help="Input PDF file path")
    args = parser.parse_args()

    pdf2md(args.input)


if __name__ == "__main__":
    main()
