# TypeScript Interface to C# Source Generator

TypeScript 인터페이스 정의를 읽어서 Unity C# 코드를 자동으로 생성하는 Roslyn Source Generator입니다.

## 🎯 기능

- TypeScript 인터페이스 파일 (`.ts`) 파싱
- `type_mappings.json`을 사용한 타입 변환
- Unity 프로젝트에서 컴파일 타임에 자동 코드 생성
- 생성된 코드는 `.g.cs` 확장자로 관리

## 🏗️ 구조

```
InterfaceCodeGen/
├── InterfaceCodeGen.csproj           # 프로젝트 파일
├── TypeScriptInterfaceGenerator.cs  # Source Generator 구현
└── README.md                         # 이 파일
```

## 🔧 빌드 방법

```bash
cd interface/InterfaceCodeGen
dotnet build -c Release
```

빌드 결과물:
- `bin/Release/netstandard2.0/InterfaceCodeGen.dll`

## 🔗 Unity 프로젝트 연동

Unity에서 Source Generator를 사용하려면 `csc.rsp` 파일이 필요합니다.

**위치:** `ar_client/Assets/csc.rsp`

**내용:**
```
-analyzer:"../../../interface/InterfaceCodeGen/bin/Release/netstandard2.0/InterfaceCodeGen.dll"
-additionalfile:"../../../interface/touch_raycast_input.ts"
-additionalfile:"../../../interface/type_mappings.json"
```

## 📝 사용 방법

### 1. TypeScript 인터페이스 작성

`interface/touch_raycast_input.ts`:
```typescript
interface Vector3 {
  x: number;
  y: number;
  z: number;
}

interface TouchStartPayload {
  targetPartIndex: number;
  actionPoint: Vector3;
}
```

### 2. 타입 매핑 설정 (선택)

`interface/type_mappings.json`:
```json
{
  "typescript_to_csharp": {
    "number": "float",
    "string": "string",
    "boolean": "bool",
    "Vector3": "Vector3"
  }
}
```

### 3. Unity에서 자동 생성

1. Source Generator 빌드 (위 참조)
2. Unity 에디터 재시작 또는 스크립트 재컴파일
3. `TouchRaycastMessage.g.cs` 자동 생성됨

**생성된 코드 예시:**
```csharp
// AUTO-GENERATED CODE - DO NOT EDIT MANUALLY
using UnityEngine;

namespace CADverse.Input
{
    [System.Serializable]
    public class Vector3
    {
        public float x;
        public float y;
        public float z;
    }

    [System.Serializable]
    public class TouchStartPayload
    {
        public float targetPartIndex;
        public Vector3 actionPoint;
    }
}
```

## 🔍 동작 원리

1. **Roslyn Compiler Integration**
   - Unity 컴파일러(Roslyn)가 Source Generator 실행
   - `csc.rsp`에 지정된 analyzer 로드

2. **AdditionalFiles 읽기**
   - `touch_raycast_input.ts` 파싱
   - `type_mappings.json` 로드

3. **코드 생성**
   - TypeScript 인터페이스 → C# 클래스 변환
   - `context.AddSource()`로 컴파일에 코드 추가

4. **자동 통합**
   - 생성된 코드는 Unity 프로젝트의 일부로 인식됨
   - IntelliSense, 자동완성 지원

## ⚙️ 타입 변환 규칙

| TypeScript | C# |
|------------|-----|
| `number` | `float` |
| `string` | `string` |
| `boolean` | `bool` |
| `Vector3` | `Vector3` |
| `"literal"` | `string` (초기값 설정) |

## 🚨 주의사항

### Unity 버전 요구사항
- **Unity 2021.2 이상** 필요
- Roslyn Source Generator 지원 버전

### .g.cs 파일 수정 금지
- 자동 생성된 파일 (`.g.cs`)은 수정하지 말 것
- TypeScript 인터페이스를 수정하면 자동으로 재생성됨

### csc.rsp 경로
- 상대 경로 사용 주의
- Unity 프로젝트 구조에 맞게 조정 필요

## 🔧 문제 해결

### 생성된 코드가 보이지 않을 때
1. Source Generator 빌드 확인
2. Unity 에디터 재시작
3. `csc.rsp` 경로 확인
4. Unity 버전 확인 (2021.2+)

### 컴파일 에러 발생 시
1. Unity Console에서 에러 메시지 확인
2. TypeScript 문법 확인 (정규식 파싱 한계)
3. `type_mappings.json` 형식 확인

### Source Generator 디버깅
- Unity는 Source Generator 에러를 콘솔에 표시
- 진단 메시지 (`TSGEN001`) 확인

## 📚 참고 자료

- [Roslyn Source Generators](https://docs.microsoft.com/en-us/dotnet/csharp/roslyn-sdk/source-generators-overview)
- [Unity and Roslyn Analyzers](https://docs.unity3d.com/Manual/roslyn-analyzers.html)
- [Source Generator Cookbook](https://github.com/dotnet/roslyn/blob/main/docs/features/source-generators.cookbook.md)

## 🚀 향후 개선

- [ ] Union type 지원 (TypeScript `type A | B`)
- [ ] 제네릭 타입 지원
- [ ] JSDoc 주석 → XML 문서 주석 변환
- [ ] 더 정교한 TypeScript 파서 (현재는 정규식 기반)
- [ ] Rust 코드 생성 지원
