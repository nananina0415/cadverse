using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using System.Collections.Generic;

namespace CADverse.Debugging
{
    /// <summary>
    /// UI 레이캐스트 디버거 - 클릭한 UI 오브젝트를 로그로 출력
    /// </summary>
    public class UIRaycastDebugger : MonoBehaviour
    {
        [Header("Settings")]
        [SerializeField] private bool enableDebug = true;

        private void Update()
        {
            // F1 키로 디버그 모드 토글 (새 Input System)
            var keyboard = Keyboard.current;
            if (keyboard != null && keyboard.f1Key.wasPressedThisFrame)
            {
                enableDebug = !enableDebug;
                UnityEngine.Debug.Log($"[UIDebugger] Debug mode: {(enableDebug ? "ON" : "OFF")}");
            }

            if (!enableDebug)
                return;

            // 마우스 클릭 감지 (새 Input System)
            var mouse = Mouse.current;
            if (mouse != null && mouse.leftButton.wasPressedThisFrame)
            {
                DebugUIRaycast(mouse.position.ReadValue());
            }
        }

        private void DebugUIRaycast(Vector2 screenPosition)
        {
            if (EventSystem.current == null)
            {
                UnityEngine.Debug.LogError("[UIDebugger] EventSystem is NULL!");
                return;
            }

            // EventSystem으로 UI 레이캐스트
            var eventData = new PointerEventData(EventSystem.current)
            {
                position = screenPosition
            };

            var results = new List<RaycastResult>();
            EventSystem.current.RaycastAll(eventData, results);

            UnityEngine.Debug.Log($"[UIDebugger] ========== Click at {screenPosition} ==========");
            UnityEngine.Debug.Log($"[UIDebugger] EventSystem: {EventSystem.current.name}");
            UnityEngine.Debug.Log($"[UIDebugger] Current Input Module: {EventSystem.current.currentInputModule?.GetType().Name ?? "NULL"}");
            UnityEngine.Debug.Log($"[UIDebugger] Raycast results: {results.Count}");

            if (results.Count == 0)
            {
                UnityEngine.Debug.LogWarning("[UIDebugger] No UI objects detected at click position!");
            }
            else
            {
                for (int i = 0; i < results.Count; i++)
                {
                    var result = results[i];
                    UnityEngine.Debug.Log($"[UIDebugger] [{i}] {result.gameObject.name} " +
                        $"(Layer: {LayerMask.LayerToName(result.gameObject.layer)}, " +
                        $"Distance: {result.distance}, " +
                        $"Module: {result.module?.GetType().Name ?? "NULL"})");
                }
            }

            UnityEngine.Debug.Log("[UIDebugger] ==========================================");
        }
    }
}
