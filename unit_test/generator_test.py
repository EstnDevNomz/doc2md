import time
import fitz


def iter_pages(doc: fitz.Document):
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        time.sleep(5)
        yield page_idx, page


if __name__ == "__main__":

    doc = fitz.open("./농협_60년사_1권.pdf")
    file_path = f"iter_test.txt"

    with open(file_path, "w", encoding="utf-8") as f:
        for page_idx, page in iter_pages(doc):
            print(f"Page {page_idx+1}/{doc.page_count}")
            print(page.get_text())
            print("-" * 40)

            f.write(page.get_text())
