import re

# main.cs에서 UpdateModelFromServer를 public으로 만들고 Update()에서 호출 제거
with open("prototype/ar_client/Assets/Scripts/main.cs", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update()에서 UpdateModelFromServer() 호출 제거
content = content.replace(
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
    """        // 바닥 터치 시 모델 배치
        if (!_isModelPlaced && _loadedModel != null && hasTouch)
        {
            PlaceModelOnPlane(touchPosition);
        }
    }""",
)

# 2. UpdateModelFromServer를 public으로 변경
content = content.replace(
    "    private void UpdateModelFromServer()",
    "    public void UpdateModelFromServer()",
)

with open("prototype/ar_client/Assets/Scripts/main.cs", "w", encoding="utf-8") as f:
    f.write(content)

print(
    "main.cs 수정 완료 - UpdateModelFromServer를 public으로 변경, Update()에서 호출 제거"
)
