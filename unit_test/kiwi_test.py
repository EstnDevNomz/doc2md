from kiwipiepy import Kiwi
import fitz

kiwi = Kiwi()


if __name__ == "__main__":
    ast = fitz.open("./한국의농협_국문.pdf")

    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)

        kiwi.analyze()
