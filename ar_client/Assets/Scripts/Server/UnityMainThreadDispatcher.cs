using System;
using System.Collections.Generic;
using UnityEngine;

namespace CADverse.Server
{
    /// <summary>
    /// 백그라운드 스레드에서 메인 스레드로 작업을 디스패치하는 유틸리티
    /// </summary>
    public class UnityMainThreadDispatcher : MonoBehaviour
    {
        private static UnityMainThreadDispatcher _instance;
        private static readonly Queue<Action> _executionQueue = new Queue<Action>();
        private static readonly object _lock = new object();

        /// <summary>
        /// 싱글톤 인스턴스
        /// </summary>
        public static UnityMainThreadDispatcher Instance
        {
            get
            {
                if (_instance == null)
                {
                    // 기존 인스턴스 찾기
                    _instance = FindObjectOfType<UnityMainThreadDispatcher>();

                    if (_instance == null)
                    {
                        // 없으면 생성
                        var go = new GameObject("UnityMainThreadDispatcher");
                        _instance = go.AddComponent<UnityMainThreadDispatcher>();
                        DontDestroyOnLoad(go);
                    }
                }

                return _instance;
            }
        }

        /// <summary>
        /// 메인 스레드에서 실행할 작업을 큐에 추가
        /// </summary>
        public static void Enqueue(Action action)
        {
            if (action == null)
            {
                return;
            }

            lock (_lock)
            {
                _executionQueue.Enqueue(action);
            }

            // 인스턴스가 없으면 생성 (자동 초기화)
            _ = Instance;
        }

        private void Update()
        {
            // 메인 스레드에서 큐에 쌓인 작업 실행
            lock (_lock)
            {
                while (_executionQueue.Count > 0)
                {
                    var action = _executionQueue.Dequeue();

                    try
                    {
                        action?.Invoke();
                    }
                    catch (Exception e)
                    {
                        Debug.LogError($"[UnityMainThreadDispatcher] Error executing action: {e}");
                    }
                }
            }
        }

        private void OnDestroy()
        {
            if (_instance == this)
            {
                _instance = null;
            }
        }
    }
}
