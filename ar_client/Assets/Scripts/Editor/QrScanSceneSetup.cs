using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.UI;
using UnityEngine.InputSystem.UI;
using UnityEngine.EventSystems;
using UnityEngine.Rendering.Universal; // For URP support

namespace CADverse.Editor
{
    public class QrScanSceneSetup
    {
        private const string SceneName = "QrScan";
        private const string MenuPath = "CADverse/Setup QrScan Scene";

        [MenuItem(MenuPath, false, 1)]
        public static void SetupQrScanScene()
        {
            if (EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
            {
                // 새 씬 생성
                var newScene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
                newScene.name = SceneName;

#pragma warning disable 0618 // Suppress obsolete warnings for ARSessionOrigin and ARPoseDriver
                // 1. AR Session Origin (AR Camera 포함)
                GameObject arSessionOriginGO = new GameObject("AR Session Origin");
                arSessionOriginGO.AddComponent<ARSessionOrigin>();
                arSessionOriginGO.AddComponent<ARPoseDriver>();
#pragma warning restore 0618

                // AR Camera 생성
                GameObject arCameraGO = new GameObject("AR Camera");
                arCameraGO.transform.SetParent(arSessionOriginGO.transform);
                Camera arCamera = arCameraGO.AddComponent<Camera>();
                arCamera.tag = "MainCamera";
                arCamera.clearFlags = CameraClearFlags.SolidColor;
                arCamera.backgroundColor = Color.black; // 카메라 피드가 뜰 때까지 검은색으로

                // URP Camera Data 추가
                arCameraGO.AddComponent<UniversalAdditionalCameraData>();

                arCameraGO.AddComponent<ARCameraManager>();
                arCameraGO.AddComponent<ARCameraBackground>();
                // arCameraGO.AddComponent<ARCameraTrackingState>(); // Removed as it causes compilation error. Tracking state can be accessed via ARCameraManager.

                // 2. AR Session
                GameObject arSessionGO = new GameObject("AR Session");
                arSessionGO.AddComponent<ARSession>();

                // 3. Canvas (UI)
                GameObject canvasGO = new GameObject("Canvas");
                Canvas canvas = canvasGO.AddComponent<Canvas>();
                canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                canvasGO.AddComponent<CanvasScaler>();
                canvasGO.AddComponent<GraphicRaycaster>();

                // EventSystem 추가 (새 Input System용)
                GameObject eventSystemGO = new GameObject("EventSystem");
                eventSystemGO.AddComponent<EventSystem>();
                eventSystemGO.AddComponent<InputSystemUIInputModule>();


                // 4. QR Scan Box UI Panel
                GameObject qrScanBoxPanelGO = new GameObject("QRScanBoxPanel");
                qrScanBoxPanelGO.transform.SetParent(canvasGO.transform, false);
                RectTransform rectTransform = qrScanBoxPanelGO.AddComponent<RectTransform>();
                rectTransform.anchorMin = Vector2.zero;
                rectTransform.anchorMax = Vector2.one;
                rectTransform.sizeDelta = Vector2.zero; // 화면 전체

                Image panelImage = qrScanBoxPanelGO.AddComponent<Image>();
                panelImage.color = new Color(0, 0, 0, 0.5f); // 반투명 검정 배경

                // 여기에 QrScanBoxUI 스크립트 추가 예정 (미리 존재해야 함)
                qrScanBoxPanelGO.AddComponent<CADverse.UI.QrScanBoxUI>(); 

                // 씬 저장
                EditorSceneManager.SaveScene(newScene, "Assets/Scenes/" + SceneName + ".unity");
                Debug.Log($"{SceneName} scene created successfully in Assets/Scenes.");
            }
        }
    }
}
