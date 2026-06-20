# Prompt Roles

각 프롬프트는 하위 Codex 실행이 맡을 한 역할만 정의한다. 하네스가 공통 규칙, 백로그 항목, 이전 산출물, 출력 경로를 앞뒤에 붙여 실행한다.

- `00_shared_rules.md`: 모든 단계의 공통 제약
- `10_idea_scout.md`: 아이디어 강구
- `15_prior_art_gate.md`: 선행기술 기반 kill-or-narrow 게이트
- `20_draft_writer.md`: 명세서/청구항 초안 작성
- `30_patentability_examiner.md`: 엄격 심사관 조사
- `40_revision_writer.md`: 거절 이유 기반 보정
- `50_finalizer.md`: 최종 출원 후보 정리
- `60_independent_verifier.md`: 산출물 독립 검증
- `65_external_prior_art_spotcheck.md`: 최종본 통과 후 외부 선행기술 보수 감사
- `70_visual_explainer.md`: 공개용 기술 설명 HTML 생성
