import os
import re
import argparse
import asyncio
import fitz
from layout_pdf2md import pdf2md


async def main():
    parser = argparse.ArgumentParser(description="PDF preprocessing tool")
    parser.add_argument("input", help="Input PDF file path")
    args = parser.parse_args()

    await pdf2md(args.input)


if __name__ == "__main__":
    asyncio.run(main())
    # main()
