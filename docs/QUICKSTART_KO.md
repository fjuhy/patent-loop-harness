# 빠른 시작 (macOS)

이 저장소 하나만 설치하면 된다. 발명 아이디어·초안·보고서는 각자 만드는 개인 워크벤치 폴더에 쌓이며, 이 저장소에는 올리지 않는다.

## 0. 준비물

- GitHub 계정과 이 저장소 접근 권한(초대 메일을 수락한다).
- LLM 실행기 하나: Codex CLI(ChatGPT 구독) 또는 Claude Code(Claude 구독). 본인 계정으로 로그인해 둔다.
- 터미널(응용 프로그램 → 유틸리티 → 터미널).

macOS 기본 `python3`는 3.9라서 이 하네스(3.11 이상 필요)를 직접 설치하면 실패한다. 아래처럼 `uv`로 설치하면 맞는 파이썬을 자동으로 받는다.

## 1. 도구 설치 (최초 1회)

```bash
# Homebrew가 없으면 https://brew.sh 안내대로 먼저 설치한다.
brew install uv gh git

# GitHub 로그인 후 git이 그 로그인을 쓰도록 연결한다(비공개 저장소 접근에 필요).
gh auth login          # GitHub.com → HTTPS → 브라우저 로그인 선택
gh auth setup-git

# LLM 실행기 중 하나를 설치하고 로그인한다.
brew install --cask codex && codex login                 # Codex를 쓸 때
# 또는 Claude Code: https://docs.anthropic.com/claude-code 안내대로 설치 후 `claude` 실행해 로그인

# 하네스 설치
uv tool install --python 3.12 git+https://github.com/fjuhy/patent-loop-harness
uv tool update-shell   # 처음 한 번. 이후 터미널을 새로 연다.
patent-loop --version
```

## 2. 개인 워크벤치 만들기

```bash
mkdir -p ~/patent-work && cd ~/patent-work
patent-loop init \
  --field "연구할 분야 이름(영문 권장)" \
  --field-description "분야 경계를 한 문장으로 설명" \
  --runner codex          # Claude Code를 쓰면 claude
patent-loop doctor        # Doctor OK가 나오면 준비 완료
patent-loop doctor --runner-smoke   # 실행기가 웹 검색까지 되는지 실제로 한 번 확인
```

`--field`를 생략하면 번들 기본 분야(배터리 산업 SW)로 동작한다. 분야는 나중에 `config/patent_loop.toml`의 `[field]`를 고쳐 바꿀 수 있다.

## 3. 돌리기

```bash
cd ~/patent-work
patent-loop scout --count 3          # 분야에 맞는 아이디어 씨앗을 선행기술 검토 후 백로그에 넣는다
patent-loop status                   # 백로그·다음 단계 확인
patent-loop run --dry-run --max-items 1   # 실제 호출 없이 다음 단계 프롬프트만 만든다
patent-loop run --max-items 1        # 한 단계 실제 실행(초안 → 심사 → 레드팀 → 수정 …)
patent-loop validate                 # 산출물 형식 검사
```

결과물 위치: `work/`(단계별 산출물), `reports/`(심사·검증 보고서), `final/`(최종 후보), `visuals/`(설명 HTML·도면).

## 4. 업데이트

```bash
uv tool upgrade patent-loop-harness
```

## 5. 주의

- 결과는 기술 초안이며 법률 의견이 아니다. 출원 전에는 변리사 검토를 받는다.
- 출원 전 공개는 신규성을 잃게 할 수 있다. 워크벤치를 GitHub에 백업하려면 반드시 **비공개(private)** 저장소로 만든다.
- 회사 업무와 관련된 발명은 직무발명 절차를 먼저 확인한다.
- 이 저장소(하네스)에는 개인 발명 내용을 커밋하지 않는다.
