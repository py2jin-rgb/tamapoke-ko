# TamaPoke KO

Waveshare **ESP32-S3-Touch-AMOLED-1.75**용 TamaPoke 비공식 한국어판입니다.

**설치 페이지: https://py2jin-rgb.github.io/tamapoke-ko/**

## ⑤ 시스템 절전 2.8

현재 개발·배포 대상은 **기존 ⑤ OTA + Volume 2.6을 이어받은 2.8 / OTA build 280**입니다. 최종 소스는 `firmware/TamaPoke/`에서 직접 관리합니다. 과거 패치 생성기를 다시 연쇄 실행해 ⑤를 만들지 않습니다.

- 무조작 30초 감광, 2분 화면 꺼짐을 기본으로 합니다. 수동 시계에도 적용합니다.
- 상시 시계는 기본 OFF이며 설정에서 선택합니다. Light-sleep은 기본 ON이며 설정에서 끌 수 있습니다. USB 연결 중에는 MCU Light-sleep을 적용하지 않습니다.
- 패널 수면·화면 전송 중단·통신 대기 제한·오디오 유휴 처리를 함께 적용합니다.
- 게임/알람/음량/한글/배틀 기능과 기존 NVS 저장 영역·키·파티션 배치를 이어받습니다.
- 새 OTA는 인증서, 정확한 파일 크기와 SHA256을 검증합니다.

**실기 배터리 지속시간·평균 전류는 아직 측정하지 않았습니다.** 컴파일·정적/정책 검사와 실기 전력 검증은 별개입니다. 구체적인 사용시간이나 절감률은 측정 후 기록합니다.

## 기존 판본과 복원 파일

① 안정판, ② Living Clock 1.9, ③ Battery 2.3, ④ Battle 2.4, 이전 ⑤ OTA + Volume 2.6은 `tools/baseline.lock.json`의 URL·크기·전체 SHA256으로 고정합니다. 새 배포에도 **동일한 BIN을 동일 경로로 보존**합니다. 2.8 절전 개선은 새 ⑤에만 들어갑니다.

기준은 커밋 `ff17be49396971d752b2061fe4997adf9a2f5cd8`의 성공 배포 #141입니다. 다섯 BIN 모두 실제 다운로드 후 SHA256을 확인했습니다. 기준 파일의 URL이 사라지거나 해시/크기가 다르면 빌드를 중단하며 다른 파일로 대체하지 않습니다. 과거 `source_package.zip`, `combo_test/`, `alarm_test/`는 복원 자료로 남겨 둡니다.

Pages에 보존하는 이전 BIN에 의존하므로, 운영자가 별도 사본 또는 성공한 Actions 릴리스 아티팩트를 보관해야 합니다. 파일을 복구할 때는 lock의 크기와 전체 SHA256이 모두 일치해야 합니다.

## 업데이트와 저장 유지

기존 ⑤ 2.6 기기는 **기기 메뉴의 Wi-Fi 업데이트를 우선 사용**합니다. OTA는 실행 중인 앱과 다른 슬롯에 새 펌웨어를 쓰고 정상 완료 후 전환합니다.

USB 설치는 아래와 같이 분리합니다. **Erase/초기화를 체크하지 마세요.**

| 매니페스트 | 기록 위치 | 용도 |
|---|---|---|
| `manifest-ota.json` | app0 `0x10000` | 현재 실행 슬롯이 app0인 기기 |
| `manifest-ota-app1.json` | app1 `0x310000` | 현재 실행 슬롯이 app1인 기기 |
| `manifest-ota-2.6.json` | app0 `0x10000` | app0에 이전 2.6 복원 |
| `manifest-ota-2.6-app1.json` | app1 `0x310000` | app1에 이전 2.6 복원 |

이 매니페스트들은 지정한 앱만 기록하며 부트로더·파티션 테이블·NVS·OTA 선택 정보를 지우거나 변경하지 않습니다. 따라서 **실행 중이지 않은 슬롯을 USB로 덮어써도 부팅 버전은 자동 전환되지 않습니다.** 슬롯을 모르면 임의로 선택하지 말고 기기 OTA를 사용하거나 실행 슬롯을 먼저 확인합니다. 새 2.8은 USB 시리얼 시작 로그에 실행 슬롯/오프셋을 표시합니다.

①~④의 기존 USB 설치 버튼은 app0 전용으로 유지됩니다. 완전 새 보드의 부트로더/파티션 설치나 microSD 자산 구성은 이 앱 업데이트 페이지의 범위에 포함되지 않습니다.

`new_install_prompt_erase: true`는 의도적인 설정입니다. ESP Web Tools의 Improv 미지원 설치 흐름에서는 이를 false로 바꾸면 전체 erase가 기본 동작이 될 수 있습니다. 현재처럼 선택창을 표시하고 **Erase를 선택하지 않는 흐름**을 유지해야 합니다.

## 고정 빌드 환경

| 항목 | 버전 |
|---|---|
| GitHub Actions OS | Ubuntu 24.04 |
| Arduino CLI | 1.3.1 |
| Arduino-ESP32 | 3.1.0 |
| GFX Library for Arduino | 1.6.7 |
| SensorLib | 0.3.1 |
| XPowersLib | 0.2.6 |
| Nanum font package | Ubuntu `fonts-nanum=20200506-1` |
| Flash / PSRAM | 16 MiB / OPI |
| Partition scheme | `app3M_fat9M_16MB` |

현대 한글 폴백 헤더는 기존 `combo_test/gen_hangul_font.py`와 Nanum 폰트/Pillow로 생성합니다. 생성된 헤더를 포함한 소스 파일 각각의 SHA256 및 전체 소스 지문을 `release.json`에 기록합니다. 폰트/OS 패키지는 환경 영향을 받을 수 있으므로 byte-for-byte 재빌드 일치까지 보장하지 않습니다.

필요한 코어·라이브러리 및 `fonts-nanum`, `python3-pil` 설치 후:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s tools -p 'test_*.py' -v
mkdir -p .build/tests
g++ -std=c++17 -Wall -Wextra -pedantic tests/test_power_policy.cpp -o .build/tests/test_power_policy
.build/tests/test_power_policy
python3 tools/build_release.py
python3 tools/package_release.py
python3 tools/validate_release.py site
```

Arduino CLI 실행 경로가 다르면 `tools/build_release.py --arduino-cli /absolute/path/to/arduino-cli`를 사용합니다. 별도 CLI 설정은 `--config-file`, 추출한 동일 Nanum TTF는 `--font`로 지정할 수 있습니다. 빌드 출력은 `.build/ota/`, 검증된 이전 BIN 캐시는 `.build/baseline-cache/`, 배포 결과는 `site/`입니다. 패키징은 완료된 `build-provenance.json`의 BIN/소스 해시와 현재 파일이 일치할 때만 진행합니다.

## 배포 절차와 검사

- `battery-*` 브랜치 push 및 main 대상 PR: 정책 검사 → 소스 계약 검사 → 단일 ⑤ 컴파일 → 이전 BIN 검증 → 패키징 검사 → 검토용 아티팩트 저장. **Pages는 변경하지 않습니다.**
- 검증한 변경을 main에 반영: 같은 검사 후 생성된 Pages 아티팩트를 배포합니다.
- `release.json`, `ota-latest.json`, 웹 USB 매니페스트, HTML 버전/소스 커밋, BIN 크기/해시가 서로 일치해야 합니다.
- OTA 메타데이터는 기존 2.6 문자열 파서도 읽을 수 있도록 공백 없는 JSON으로 출력하고 `size`를 정확한 바이트 수로 포함합니다.
- 기존 ①~④ 및 ⑤2.6 BIN이 한 개라도 빠지거나 달라지면 배포를 중단합니다.
- `SHA256SUMS.txt`에 배포 파일들의 체크섬을 기록합니다. 소스 커밋과 생성 헤더까지 포함한 소스 지문은 `release.json`에 남깁니다.
- 배포 후 실제 URL의 `release.json`/`ota-latest.json`과 새 BIN을 다시 읽어 버전·커밋·크기·SHA256을 확인합니다.

배포 완료 후 `python3 tools/verify_published.py --expected-commit <main의 전체 커밋 SHA>`로 공개 URL의 전체 체크섬과 8개 설치 매니페스트, 보존 BIN까지 다시 검증할 수 있습니다.

실기 확인에서는 터치/PWR/알람 복귀, 무음 후 소리 재생, 통신 종료, 게임/이름/알람/음량 저장, USB 연결·분리, 현재 앱 슬롯에 맞는 USB/OTA 업데이트를 확인합니다. 전류는 동일 기기·배터리·밝기·사용 패턴으로 비교하며 화면 ON/감광/화면 OFF/알람/통신 상태를 나누어 기록합니다.

---

# ⚠️ 비공식 · 비상업적 팬 프로젝트

TamaPoke KO는 개인이 취미로 제작·유지하는 **무료·비상업적 한국어 현지화/수정 프로젝트**입니다.

이 저장소와 GitHub Pages의 펌웨어 설치 페이지는 Nintendo, Creatures Inc., GAME FREAK inc., The Pokémon Company, The Pokémon Company International 또는 그 관계사와 **제휴·후원·승인·공식 관계가 없습니다.**

Pokémon 관련 명칭, 캐릭터, 디자인, 로고, 상표, 이미지 및 기타 지식재산은 Nintendo / Creatures Inc. / GAME FREAK inc. 및 기타 해당 권리자에게 귀속됩니다. 이 저장소는 그러한 권리에 대한 소유권이나 별도 사용허가를 주장하지 않습니다.

**비영리 또는 팬 프로젝트라는 사실만으로 제3자 IP 사용 허가가 생기는 것은 아닙니다.** 이 저장소는 `비영리`, `팬 프로젝트`, `교육용` 등의 표현을 법적 면책이나 공식 허가로 주장하지 않습니다.

## 이 배포 페이지가 제공하는 것 / 제공하지 않는 것

현재 GitHub Pages 온라인 설치기는 TamaPoke KO의 **앱 펌웨어 BIN** 업데이트를 제공합니다.

이 저장소의 온라인 설치 페이지는 다음 파일을 배포하지 않습니다.

- Pokémon 게임 ROM / ISO
- 게임기 BIOS
- 상용 게임 데이터 파일
- microSD용 Pokémon 스프라이트 팩의 별도 다운로드 패키지

외부 출처에서 스프라이트나 기타 제3자 자료를 별도로 취득하는 경우, 사용자가 해당 자료의 라이선스·저작권·이용조건을 직접 확인해야 합니다.

---

# 📜 라이선스

## TamaPoke 원작 코드

이 프로젝트는 **socquique / Quique Tortosa의 TamaPoke**를 기반으로 합니다.

- Original project: https://github.com/socquique/TamaPoke
- Original web installer: https://socquique.github.io/TamaPoke/web/

원작 TamaPoke의 펌웨어/도구 소스코드는 **MIT License**로 공개되어 있으며, 이 저장소는 원작 저작권 고지와 MIT 허가문을 `LICENSE`에 보존합니다.

이 저장소에서 새로 작성된 한국어 현지화 및 소프트웨어 수정분도 각 기여자가 권리를 보유하는 범위에서 MIT License로 제공합니다.

**MIT License는 Pokémon 관련 명칭·캐릭터·디자인·스프라이트·상표 등 제3자 지식재산에 대한 사용 허가가 아닙니다.**

자세한 내용:

- [LICENSE](LICENSE)
- [LEGAL.md](LEGAL.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

---

# 💸 비상업 운영 방침

이 저장소와 공개 펌웨어 설치 페이지 자체는 무료·비상업적으로 운영합니다.

- 펌웨어 설치에 대한 요금 없음
- 유료 다운로드 없음
- 유료 회원 전용 배포 없음
- 이 설치 페이지에 대한 광고·후원 대가 없음
- Pokémon/제3자 비상업 자산을 공식 상품처럼 표시하거나 라이선스 상품으로 주장하지 않음

이 운영 방침은 **MIT 소프트웨어 코드 자체의 라이선스를 비상업 라이선스로 변경하는 것이 아닙니다.** 소프트웨어 코드의 MIT 조건과 Pokémon/제3자 자산의 권리는 서로 구분됩니다.

Pokémon 또는 제3자 비상업 라이선스 자산이 포함된 형태의 유료 판매·유료 번들에 대해서는 이 저장소가 어떠한 권리도 부여할 수 없습니다.

---

# 🎨 제3자 자산

원작 TamaPoke는 PMD SpriteCollab / SpriteCollab의 픽셀 아트를 사용하며, 원작 프로젝트는 해당 자산에 **CC BY-NC 4.0 등 원 출처의 조건**이 적용된다고 고지하고 있습니다.

개별 작가 표시와 정확한 이용조건은 반드시 원 출처에서 확인하십시오.

- SpriteCollab: https://github.com/PMDCollab/SpriteCollab
- 상세 출처: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

---

# 🛡️ 무보증 / 사용자 책임

펌웨어와 설치 도구는 MIT License에 따라 **AS IS(현 상태 그대로), 무보증**으로 제공됩니다.

기기 개조·플래싱 과정에서 발생할 수 있는 데이터 손실, 부팅 문제, 호환성 문제 등에 대비해 사용자는 필요한 데이터를 직접 백업하고 자신의 하드웨어와 설치 조건을 확인해야 합니다.

이 저장소의 설명이나 고지는 제3자 자료를 사용할 수 있는 별도의 법적 허가를 보증하지 않습니다.

---

# 📩 권리자 요청 / Takedown

본 프로젝트는 원작자와 제3자 권리자의 권리를 존중합니다.

권리자 또는 정당한 대리인이 특정 콘텐츠에 대해 권리 침해 우려를 제기하는 경우, 구체적인 대상과 권리 근거를 알려주시면 검토 후 필요한 경우 수정·비공개·삭제 등의 조치를 검토하겠습니다.

- Repository: https://github.com/py2jin-rgb/tamapoke-ko
- Issues: https://github.com/py2jin-rgb/tamapoke-ko/issues

더 자세한 법적/운영 고지는 [LEGAL.md](LEGAL.md)를 참고하십시오.

---

## Credits

TamaPoke KO is based on **TamaPoke by socquique / Quique Tortosa**.

Thank you to the original author and the open-source/community projects credited in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
