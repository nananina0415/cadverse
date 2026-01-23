using UnityEngine;
using UnityEngine.EventSystems;
using UnityEditor;
using UnityEditor.SceneManagement;

namespace CADverse.Editor
{
    /// <summary>
    /// EventSystem을 새 Input System에 맞게 자동 수정
    /// </summary>
    [InitializeOnLoad]
    public class FixEventSystem
    {
        static FixEventSystem()
        {
            // 씬이 열릴 때마다 자동으로 EventSystem 수정
            EditorSceneManager.sceneOpened += OnSceneOpened;
        }

        private static void OnSceneOpened(UnityEngine.SceneManagement.Scene scene, OpenSceneMode mode)
        {
            // 씬이 로드되고 나서 약간의 딜레이 후 실행
            EditorApplication.delayCall += () =>
            {
                FixInputSystemEventSystem(false);
            };
        }

        [MenuItem("CADverse/Fix EventSystem for New Input System")]
        public static void FixInputSystemEventSystemMenu()
        {
            FixInputSystemEventSystem(true);
        }

        private static void FixInputSystemEventSystem(bool showLog)
        {
            // 씬에서 EventSystem 찾기
            var eventSystem = Object.FindFirstObjectByType<EventSystem>();

            if (eventSystem == null)
            {
                if (showLog)
                {
                    Debug.LogWarning("[FixEventSystem] EventSystem not found in scene! Creating one...");
                }

                // EventSystem 생성
                var go = new GameObject("EventSystem");
                eventSystem = go.AddComponent<EventSystem>();
                eventSystem.gameObject.AddComponent<UnityEngine.InputSystem.UI.InputSystemUIInputModule>();

                if (showLog)
                {
                    Debug.Log("[FixEventSystem] Created EventSystem with InputSystemUIInputModule");
                }
                return;
            }

            // StandaloneInputModule 제거
            var standaloneModule = eventSystem.GetComponent<StandaloneInputModule>();
            if (standaloneModule != null)
            {
                if (showLog)
                {
                    Debug.Log("[FixEventSystem] Removing legacy StandaloneInputModule");
                }
                Object.DestroyImmediate(standaloneModule);
            }

            // InputSystemUIInputModule 추가 (새 Input System용)
            var inputSystemModule = eventSystem.GetComponent<UnityEngine.InputSystem.UI.InputSystemUIInputModule>();
            if (inputSystemModule == null)
            {
                if (showLog)
                {
                    Debug.Log("[FixEventSystem] Adding InputSystemUIInputModule");
                }
                inputSystemModule = eventSystem.gameObject.AddComponent<UnityEngine.InputSystem.UI.InputSystemUIInputModule>();
            }

            // Default Actions 생성 (actionsAsset이 null이면)
            if (inputSystemModule != null)
            {
                var actionsAssetProperty = inputSystemModule.GetType().GetProperty("actionsAsset");
                if (actionsAssetProperty != null)
                {
                    var currentAsset = actionsAssetProperty.GetValue(inputSystemModule);
                    if (currentAsset == null)
                    {
                        if (showLog)
                        {
                            Debug.Log("[FixEventSystem] Creating default Input Actions for UI");
                        }

                        // CreateDefaultActionAsset 메서드 호출
                        var createMethod = inputSystemModule.GetType().GetMethod("CreateDefaultActionAsset",
                            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic);

                        if (createMethod != null)
                        {
                            var defaultAsset = createMethod.Invoke(null, null);
                            actionsAssetProperty.SetValue(inputSystemModule, defaultAsset);
                            EditorUtility.SetDirty(inputSystemModule);
                        }
                    }
                }
            }

            if (showLog)
            {
                Debug.Log("[FixEventSystem] EventSystem is now using new Input System! UI buttons should work.");
            }
        }
    }
}
