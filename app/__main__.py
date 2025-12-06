import os
import argparse
from .core import get_md_by_pdf

def main():
    parser = argparse.ArgumentParser(description="PDF preprocessing tool")
    parser.add_argument("input", help="Input PDF file path")
    args = parser.parse_args()
    
    text = get_md_by_pdf(args.input)
    
    name, ext = os.path.splitext(args.input)
    with open(f'{name}.md', "w", encoding="utf-8") as f:
        f.write(text)

if __name__ == "__main__":
    main()