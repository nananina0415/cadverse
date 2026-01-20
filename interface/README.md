# CADverse Interface Definitions

클라이언트-서버 간 통신 인터페이스를 정의하는 디렉토리입니다.

## 📁 파일 구조

```
interface/
├── README.md                          # 이 파일
├── touch_raycast_input.ts             # 터치 레이캐스트 입력 인터페이스
├── type_mapping/                      # 타입 매핑 설정
│   ├── client.json                    # TypeScript → C# 매핑
│   └── server.json                    # TypeScript → Rust 매핑
├── codegen/                           # 코드 생성기
│   ├── client/                        # C# Source Generator
│   │   ├── InterfaceCodeGen.csproj
│   │   ├── src/
│   │   │   └── TypeScriptInterfaceGenerator.cs
│   │   └── README.md
│   └── server/                        # Rust Procedural Macro
│       ├── Cargo.toml
│       ├── src/
│       │   └── lib.rs
│       └── README.md
├── plugin_to_server/                  # 플러그인 → 서버 메시지
└── (향후 추가될 인터페이스들)
```

## 🎯 인터페이스 작성 방식

### TypeScript 형식 사용

JSON Schema 대신 **TypeScript 인터페이스 형식**을 사용합니다.

**이유:**
- 사람이 읽기 쉬움
- 주석으로 설명 추가 가능
- IDE 자동완성 지원
- 타입 체크 가능

**예시:**
```typescript
interface Vector3 {
  x: number;
  y: number;
  z: number;
}

interface TouchStartPayload {
  /** 터치한 부품의 인덱스 */
  targetPartIndex: number;

  /** 터치 지점 (부품 로컬 좌표) */
  actionPoint: Vector3;
}
```

## 🔄 코드 생성 방법

### C# (Unity) 코드 생성 - **자동 (Source Generator)**

TypeScript 인터페이스에서 **C# Source Generator**를 사용하여 자동으로 생성됩니다.

**설정:**
1. Source Generator 빌드:
   ```bash
   cd interface/codegen/client
   dotnet build -c Release
   ```

2. Unity 프로젝트에 `csc.rsp` 파일이 설정됨 (이미 완료)

3. TypeScript 인터페이스 수정 후 Unity 재컴파일 시 자동 생성

**생성 위치:**
- `CADverse.Input` 네임스페이스
- 파일명: `TouchRaycastMessage.g.cs` (자동 생성, 수동 편집 금지)

**타입 매핑:**
- `type_mapping/client.json` 파일에서 관리
- TypeScript 타입 → C# 타입 자동 변환

**예시:**
```typescript
// TypeScript 정의
interface TouchStartPayload {
  targetPartIndex: number;
  actionPoint: Vector3;
}

// 자동 생성되는 C# 코드
[System.Serializable]
public class TouchStartPayload
{
    public float targetPartIndex;
    public Vector3 actionPoint;
}
```

**자세한 내용:** [codegen/client/README.md](codegen/client/README.md)

### Rust 코드 생성 - **자동 (Procedural Macro)**

TypeScript 인터페이스에서 **Rust Procedural Macro**를 사용하여 자동으로 생성됩니다.

**설정:**
1. Cargo.toml에 의존성 추가:
   ```toml
   [dependencies]
   interface_codegen_macro = { path = "../interface/codegen/server" }
   serde = { version = "1.0", features = ["derive"] }
   serde_json = "1.0"
   ```

2. Rust 코드에서 매크로 사용:
   ```rust
   use interface_codegen_macro::generate_from_typescript;

   generate_from_typescript!("touch_raycast_input.ts");
   ```

**타입 매핑:**
- `type_mapping/server.json` 파일에서 관리
- TypeScript 타입 → Rust 타입 자동 변환
- 필드명: camelCase → snake_case 자동 변환

**예시:**
```typescript
// TypeScript 정의
interface TouchStartPayload {
  targetPartIndex: number;
  actionPoint: Vector3;
}

// 자동 생성되는 Rust 코드
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TouchStartPayload {
    pub target_part_index: f32,
    pub action_point: Vector3,
}
```

**자동 기능:**
- `#[serde(rename_all = "camelCase")]`: JSON 직렬화 시 camelCase 변환
- `#[derive(Debug, Clone, Serialize, Deserialize)]`: serde 자동 구현
- 컴파일 타임 타입 검증

**자세한 내용:** [codegen/server/README.md](codegen/server/README.md)

## 📝 작성 규칙

### 1. 메시지 구조

모든 메시지는 `type`과 `payload`를 가집니다:

```typescript
interface SomeMessage {
  type: "MessageType";
  payload: SomePayload;
}
```

### 2. 네이밍 컨벤션

- **TypeScript**: camelCase
  - `targetPartIndex`, `fingerPoint`
- **Rust**: snake_case (변환 필요)
  - `target_part_index`, `finger_point`
  - `#[serde(rename = "...")]`로 JSON 필드명 매핑
- **C#**: camelCase (TypeScript와 동일)
  - `targetPartIndex`, `fingerPoint`

### 3. 타입 매핑

| TypeScript | Rust | C# |
|------------|------|-----|
| `number` | `f32` 또는 `i32` | `float` 또는 `int` |
| `string` | `String` | `string` |
| `boolean` | `bool` | `bool` |
| `Vector3` | `Vector3` | `Vector3Data` |
| `{}` (empty) | `serde_json::Value` | `object` |

### 4. Union Types

TypeScript:
```typescript
type Input = MessageA | MessageB | MessageC;
```

Rust:
```rust
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum Input {
    MessageA { payload: PayloadA },
    MessageB { payload: PayloadB },
    MessageC { payload: PayloadC },
}
```

C#:
```csharp
// Union은 없으므로 개별 클래스로 처리
// 파싱 시 type 필드로 구분
```

## 🔍 검증 방법

### 1. 수동 검증
- TypeScript 정의 읽기
- Rust/C# 코드와 비교
- 필드명, 타입 확인

### 2. 런타임 테스트
- 클라이언트에서 메시지 전송
- 서버에서 수신 및 파싱 확인
- 로그로 필드값 검증

### 3. 예시 데이터
각 인터페이스 파일 하단에 JSON 예시 추가:

```typescript
/**
 * 사용 예시:
 * {
 *   "type": "TouchStart",
 *   "payload": {
 *     "targetPartIndex": 0,
 *     "actionPoint": { "x": 0.5, "y": 0.2, "z": -0.1 }
 *   }
 * }
 */
```

## 🚀 새 인터페이스 추가하기

1. **TypeScript 정의 작성**
   - `interface/` 디렉토리에 `.ts` 파일 생성
   - 인터페이스 정의 및 주석 작성
   - 사용 예시 추가

2. **C# 코드 자동 생성 (Source Generator)**
   - Source Generator 빌드: `cd interface/codegen/client && dotnet build -c Release`
   - TypeScript 파일 저장 후 Unity 에디터 재시작 또는 재컴파일
   - `TouchRaycastMessage.g.cs` 자동 생성됨
   - 생성된 파일은 수정하지 말 것 (.g.cs 파일)

3. **Rust 구조체 자동 생성 (Procedural Macro)**
   - Rust 코드에서 매크로 사용: `generate_from_typescript!("파일명.ts");`
   - 컴파일 시 자동으로 구조체 생성
   - serde derive 및 camelCase 변환 자동 적용

4. **타입 매핑 업데이트 (필요시)**
   - C#: `type_mapping/client.json`에 커스텀 타입 추가
   - Rust: `type_mapping/server.json`에 커스텀 타입 추가
   - Source Generator가 새 타입 인식

5. **문서 업데이트**
   - 이 README에 새 인터페이스 링크 추가
   - 구현 계획 문서 업데이트

## 📚 참고 자료

- [TypeScript Documentation](https://www.typescriptlang.org/docs/)
- [Serde Documentation](https://serde.rs/)
- [Unity JsonUtility](https://docs.unity3d.com/ScriptReference/JsonUtility.html)

---

**Sources:**
- [Schemars](https://github.com/GREsau/schemars)
- [Synchronizing Rust Types with Typescript](https://imfeld.dev/writing/generating_typescript_types_from_rust)
- [Publishing Rust types to a TypeScript frontend](https://cetra3.github.io/blog/sharing-types-with-the-frontend/)
