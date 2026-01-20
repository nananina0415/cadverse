# Rust Interface Code Generator (Procedural Macro)

TypeScript 인터페이스 정의에서 Rust 구조체를 자동 생성하는 procedural macro입니다.

## 🎯 기능

- TypeScript 인터페이스 파일 (`.ts`) 파싱
- `type_mapping/server.json`을 사용한 타입 변환
- 컴파일 타임에 Rust 구조체 자동 생성
- serde 자동 derive 및 camelCase 변환 설정

## 📦 사용 방법

### 1. Cargo.toml에 의존성 추가

```toml
[dependencies]
interface_codegen_macro = { path = "../../interface/codegen/server" }
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
```

### 2. Rust 코드에서 매크로 사용

```rust
use interface_codegen_macro::generate_from_typescript;

// TypeScript 인터페이스에서 Rust 구조체 자동 생성
generate_from_typescript!("touch_raycast_input.ts");

// 생성된 구조체 사용
fn main() {
    let payload = TouchStartPayload {
        target_part_index: 0,
        action_point: Vector3 { x: 1.0, y: 2.0, z: 3.0 },
        finger_point: Vector3 { x: 0.0, y: 0.0, z: 0.0 },
        z_direction: Vector3 { x: 0.0, y: 0.0, z: 1.0 },
    };

    let json = serde_json::to_string(&payload).unwrap();
    println!("{}", json);
}
```

## 🔄 생성되는 코드 예시

TypeScript 입력:
```typescript
interface Vector3 {
  x: number;
  y: number;
  z: number;
}

interface TouchStartPayload {
  targetPartIndex: number;
  actionPoint: Vector3;
  fingerPoint: Vector3;
  z_direction: Vector3;
}
```

생성되는 Rust 코드:
```rust
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Vector3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TouchStartPayload {
    pub target_part_index: f32,
    pub action_point: Vector3,
    pub finger_point: Vector3,
    pub z_direction: Vector3,
}
```

## ⚙️ 타입 매핑

`type_mapping/server.json` 참조:

| TypeScript | Rust |
|------------|------|
| `number` | `f32` |
| `string` | `String` |
| `boolean` | `bool` |
| `Vector3` | `Vector3` |

## 🔍 동작 원리

1. **컴파일 타임 실행**
   - Procedural macro는 Rust 컴파일 시 실행됨
   - `generate_from_typescript!()` 호출 시점에 TypeScript 파일 읽기

2. **파일 찾기**
   - 현재 디렉토리에서 상위로 올라가며 `interface/` 폴더 탐색
   - `interface/touch_raycast_input.ts` 읽기
   - `interface/type_mapping/server.json` 읽기

3. **파싱 및 변환**
   - 정규식으로 TypeScript 인터페이스 파싱
   - 필드명: camelCase → snake_case 변환
   - 타입: type_mapping.json 기반 변환

4. **코드 생성**
   - `syn`, `quote` 크레이트 사용
   - Rust 구조체 토큰 생성
   - serde derive 및 속성 자동 추가

## 📝 네이밍 컨벤션

- **TypeScript**: `camelCase` (targetPartIndex)
- **Rust 필드명**: `snake_case` (target_part_index)
- **JSON 직렬화**: `camelCase` (#[serde(rename_all = "camelCase")])

예시:
```rust
pub struct TouchStartPayload {
    pub target_part_index: f32,  // Rust 필드명: snake_case
}

// JSON으로 직렬화하면: {"targetPartIndex": 0}  (camelCase)
```

## 🚨 주의사항

### 빌드 시점
- 매크로는 **컴파일 타임**에 실행됨
- TypeScript 파일 수정 후 Rust 프로젝트 재빌드 필요

### 파일 경로
- `interface/` 폴더가 프로젝트 루트에서 5단계 이내에 있어야 함
- 그렇지 않으면 panic 발생

### 타입 매핑
- 매핑되지 않은 타입은 그대로 사용됨
- 커스텀 타입은 직접 정의 필요

## 🔧 문제 해결

### "interface directory not found" 에러
- 프로젝트 구조 확인
- `interface/` 폴더가 올바른 위치에 있는지 확인

### 타입 변환 에러
- `type_mapping/server.json` 확인
- 커스텀 타입이 매핑 테이블에 있는지 확인

### 빌드 느림
- Procedural macro는 컴파일 시간 증가
- 증분 컴파일이 도움될 수 있음

## 📚 참고 자료

- [The Rust Proc Macro Book](https://danielkeep.github.io/tlborm/book/)
- [syn Documentation](https://docs.rs/syn/)
- [quote Documentation](https://docs.rs/quote/)
- [Procedural Macros](https://doc.rust-lang.org/reference/procedural-macros.html)
