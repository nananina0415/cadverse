using UnityEngine;

namespace CADverse.Utils
{
    /// <summary>
    /// Android Toast 메시지를 표시하는 유틸리티 클래스
    /// </summary>
    public static class AndroidToast
    {
        /// <summary>
        /// Toast 메시지를 화면에 표시
        /// </summary>
        /// <param name="message">표시할 메시지</param>
        /// <param name="lengthLong">true면 긴 시간(3.5초), false면 짧은 시간(2초)</param>
        public static void Show(string message, bool lengthLong = false)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                AndroidJavaClass unityPlayer = new AndroidJavaClass("com.unity3d.player.UnityPlayer");
                AndroidJavaObject currentActivity = unityPlayer.GetStatic<AndroidJavaObject>("currentActivity");
                AndroidJavaObject context = currentActivity.Call<AndroidJavaObject>("getApplicationContext");

                currentActivity.Call("runOnUiThread", new AndroidJavaRunnable(() =>
                {
                    AndroidJavaClass toastClass = new AndroidJavaClass("android.widget.Toast");
                    int length = lengthLong ? 1 : 0; // LENGTH_LONG = 1, LENGTH_SHORT = 0
                    AndroidJavaObject toast = toastClass.CallStatic<AndroidJavaObject>("makeText", context, message, length);
                    toast.Call("show");
                }));
            }
            catch (System.Exception ex)
            {
                Debug.LogError($"[AndroidToast] 에러: {ex.Message}");
            }
#else
            // 에디터나 다른 플랫폼에서는 Debug.Log로 대체
            Debug.Log($"[Toast] {message}");
#endif
        }
    }
}
