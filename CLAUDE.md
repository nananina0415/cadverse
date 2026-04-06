# 빌드 레이어 원칙

각 빌드 레이어는 하위 빌드 레이어가 처리할 수 없는 것만 담당한다.
상위 레이어일수록 더 적게 해야 한다.

## 이 프로젝트의 빌드 레이어 예시

```
shell (build-server.ps1)
  └── cargo (build.rs)
        └── conda-pack
```

- **shell**: conda 탐색, 환경 생성, 환경 활성화 담당
  - conda 탐색: cargo 실행 전 시점이므로 shell이 처리
  - 환경 생성: `conda activate` 전에 환경이 존재해야 하므로 shell이 처리 (cargo는 activate 이후에 실행되므로 담당 불가)
  - 환경 활성화: PATH 설정은 shell만 할 수 있음
- **cargo (build.rs)**: 환경 업데이트, conda-pack 번들링 담당
  - 환경 업데이트: 환경이 이미 존재하는 시점이므로 cargo가 처리 가능. `environment.yml` 변경 시 자동 재실행
  - conda-pack: release 빌드 시에만 실행

## 원칙 위반 예시

```powershell
# 잘못된 예 - shell에서 conda env update를 직접 호출
conda env update -f environment.yml  # cargo(build.rs)에서 할 수 있으므로 여기 있으면 안 됨
cargo build
```

## 비고

"상위"는 실행 순서가 앞선다는 의미이지, 더 중요하다는 뜻이 아니다.