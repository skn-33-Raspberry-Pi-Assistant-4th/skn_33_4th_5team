# JSON Schema

이 디렉터리의 파일은 sLLM·RAG·챗봇·Streamlit 사이의 버전 고정 계약이다.

- `condition.schema.json`: sLLM 조건 추출 결과
- `search-response.schema.json`: RAG 검색 결과와 출처 metadata
- `chat-response.schema.json`: 챗봇이 Streamlit에 반환하는 최종 응답(`1.2.0`부터 citation-linked media 포함)
- `quiz-response.schema.json`: Mini Challenge가 frontend에 반환하는 최종 퀴즈 응답

원본 모델은 `src/contracts/models.py`다. Schema 파일을 직접 수정하지 말고 모델을 변경한 뒤 아래 명령으로 다시 생성한다.

```bash
python -m src.contracts.export_schemas
```

호환되지 않는 필드 변경에는 `schema_version` 증가와 관련 학습·평가 데이터 갱신이 필요하다.
