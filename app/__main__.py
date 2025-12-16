import os
import re
import argparse
import asyncio
import fitz
from app import *
from .core import iter_page_pipeline
from .services.text_analizer import (
    collect_header_footer_candidates,
    get_body_font_style,
    analize_morphemes,
    normalize_synonym_tokens,
    iter_tf_idf_keywords,
)


@atimeit
async def get_pdf_ast_from(file_path: str):
    ast = fitz.open(file_path)
    return ast.page_count, ast


@atimeit
async def analize_pdf(doc: fitz.Document):
    tasks = [
        collect_header_footer_candidates(doc),  # TODO: 헤더 푸터 메타로 활용 예정
        get_body_font_style(doc),  # 본문 폰트 크기
    ]
    results = asyncio.gather(*tasks)

    return await results


async def main():
    parser = argparse.ArgumentParser(description="PDF preprocessing tool")
    parser.add_argument("input", help="Input PDF file path")
    args = parser.parse_args()
    name, ext = os.path.splitext(args.input)

    # PDF 추상 객체를 가져온다
    total_index, ast = await get_pdf_ast_from(args.input)

    # PDF 전체 분석 집계 결과 -> 파이프라인 ingestion
    header_or_footer, body_styles = await analize_pdf(ast)

    file_text: str = ""
    # run file streaming: 정규화
    for page_idx, page in iter_page_pipeline(ast, header_or_footer, body_styles):
        print(f"Page {page_idx+1}/{total_index}")
        file_text += page

    # 형태소분석(불용어, 복합병사 2-gram 보정) -> TF-IDF 분류 -> 라벨링
    with open(f"{name}.md", "w", encoding="utf-8") as f:
        _morphemes: List[List[str]] = []
        
        # <SEP> 태그로 섹션을 분할한다
        sections = file_text.split(f"<{SEP}>")
        
        for section in sections:
            # 섹션 단위 형태소 분석
            _nouns = analize_morphemes(section, 50)
            _morphemes.append(_nouns)

        # 명사 동의어 표준화
        morphemes = [
            normalize_synonym_tokens(doc, SYN_MAP) for doc in _morphemes
        ]

        # TF-IDF 수행하여 도메인 후보 명사를 추출 -> Meta 필드 추가
        for i, keywords in iter_tf_idf_keywords(morphemes, 3):
            # 본문 내용이 너무 없으면 메타 안넣음
            if len(sections[i]) > 100 or len(keywords) > 0:
                _keys = [k[0] for k in keywords]
                _meta = f'[[META]] keywords: {",".join(_keys)}\n'
                sections[i] = re.sub(f"<{META}>", _meta, sections[i])
            else:
                sections[i] = re.sub(f"<{META}>", "", sections[i])
                
            f.write(sections[i])

        # with open(f"형태소분석_2_gram.md", "a") as f:
        #     f.write(str(keywords_ls) + "\n")

if __name__ == "__main__":
    asyncio.run(main())
    # main()
