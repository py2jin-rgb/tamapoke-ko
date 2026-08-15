# TamaPoke KO

Waveshare **ESP32-S3-Touch-AMOLED-1.75**용 TamaPoke 비공식 한국어 현지화/기능 수정 프로젝트입니다.

온라인 설치:

**https://py2jin-rgb.github.io/tamapoke-ko/**

## 현재 배포

- 안정판: CLEAN v1.2 기반 한국어판
- 알람 기능: 별도 테스트판으로 제공
- 웹 설치: ESP Web Tools
- 플래시 방식: 앱 영역 `0x10000` 업데이트
- 기존 NVS/세이브 및 microSD 데이터 유지 목적
- 설치 시 **전체 Erase/초기화를 선택하지 마세요.**

GitHub Actions가 검증된 소스를 ESP32-S3용 앱 BIN으로 컴파일하고 GitHub Pages에 온라인 설치 페이지를 배포합니다.

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
