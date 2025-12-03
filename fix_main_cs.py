import re

# main.cs 파일 읽기
with open("prototype/ar_client/Assets/Scripts/main.cs", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update() 메서드 끝에 모델 업데이트 코드 추가
update_addition = """
        // 모델이 배치된 후 서버 데이터로 업데이트
        if (_isModelPlaced && _loadedModel != null && simServer.IsConnected)
        {
            UpdateModelFromServer();
        }"""

# Update() 메서드 내부의 마지막 } 바로 앞에 추가
content = content.replace(
    """        // 바닥 터치 시 모델 배치
        if (!_isModelPlaced && _loadedModel != null && hasTouch)
        {
            PlaceModelOnPlane(touchPosition);
        }
    }""",
    """        // 바닥 터치 시 모델 배치
        if (!_isModelPlaced && _loadedModel != null && hasTouch)
        {
            PlaceModelOnPlane(touchPosition);
        }

        // 모델이 배치된 후 서버 데이터로 업데이트
        if (_isModelPlaced && _loadedModel != null && simServer.IsConnected)
        {
            UpdateModelFromServer();
        }
    }""",
)

# 2. OnDestroy() 앞에 UpdateModelFromServer() 메서드 추가
update_method = """
    private void UpdateModelFromServer()
    {
        var states = simServer.GetLatestModelState();

        for (int i = 0; i < states.Count && i < _loadedModel.GetPartCount(); i++)
        {
            var part = _loadedModel.GetPart(i);
            var state = states[i];

            // 위치와 회전 업데이트
            part.transform.localPosition = new Vector3(
                state.position.x,
                state.position.y,
                state.position.z
            );
            part.transform.localRotation = new Quaternion(
                state.rotation.x,
                state.rotation.y,
                state.rotation.z,
                state.rotation.w
            );
        }
    }

"""

content = content.replace(
    "    void OnDestroy()", update_method + "    void OnDestroy()"
)

# 파일 저장
with open("prototype/ar_client/Assets/Scripts/main.cs", "w", encoding="utf-8") as f:
    f.write(content)

print("main.cs 수정 완료")
