# doc2md

`doc2md`는 다양한 형식의 문서를 지능적으로 Markdown 전처리 결과로 변환하려는 프로젝트입니다. 현재는 초기 단계로, 패키지 배포 표준(PEP 621)과 `wheel` 빌드 구성을 갖춘 기본 스캐폴딩을 제공합니다.

## 설치
PyPI에 게시된 후 다음과 같이 설치할 수 있습니다:

```bash
pip install doc2md
```

## 소스에서 빌드 및 배포 아티팩트 생성
소스 코드를 받아 직접 `wheel`을 만들거나 테스트할 때는 다음 절차를 사용하세요.

1. 필요한 빌드 도구 설치
   ```bash
   python -m pip install --upgrade build
   ```
2. 프로젝트 루트에서 빌드 실행 (`dist/`에 `.whl`과 `.tar.gz`가 생성됩니다)
   ```bash
   python -m build
   ```
3. 생성된 아티팩트를 테스트 설치하거나(예: `pip install dist/doc2md-*.whl`) 배포 파이프라인에 연결할 수 있습니다.

## 개발 참고 사항
- 패키지 메타데이터와 빌드 설정은 `pyproject.toml`에 정의되어 있습니다.
- 소스 코드는 `src/` 하위에 두며, 패키지 버전은 `doc2md.__version__`을 업데이트해 관리합니다.
- 라이선스는 MIT이며, `LICENSE` 파일에 포함되어 있습니다.

기능 구현이 추가되면 CLI/API 사용법, 지원 포맷, 테스트 전략을 README에 확장해주세요.
