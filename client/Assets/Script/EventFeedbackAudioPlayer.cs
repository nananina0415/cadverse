using System.Collections.Generic;
using UnityEngine;

namespace Cadverse
{
    /// <summary>
    /// EventFeedback의 soundId / soundType / volume / pitch 값을 바탕으로
    /// Unity 클라이언트에서 알림음을 재생하는 독립 컴포넌트.
    ///
    /// 레이어 규칙:
    /// - P2PNet / P2PConn / Server / ARScene을 직접 참조하지 않는다.
    /// - 네트워크 수신을 하지 않는다.
    /// - 시뮬레이션 계산을 하지 않는다.
    /// - EventFeedback 하나만 받아서 AudioSource로 재생한다.
    /// </summary>
    public class EventFeedbackAudioPlayer : MonoBehaviour
    {
        public static EventFeedbackAudioPlayer Instance { get; private set; }

        const string ResourceRoot = "Audio/EventFeedback";
        const float DefaultVolume = 0.8f;
        const float DefaultPitch = 1.0f;
        const float DefaultCooldownSec = 0.5f;

        readonly Dictionary<string, AudioClip> _clipCache = new();
        readonly Dictionary<string, float> _lastPlayedAt = new();

        AudioSource _audioSource;

        public static EventFeedbackAudioPlayer Ensure()
        {
            if (Instance != null)
                return Instance;

            var go = new GameObject("EventFeedbackAudioPlayer");
            DontDestroyOnLoad(go);
            return go.AddComponent<EventFeedbackAudioPlayer>();
        }

        void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            DontDestroyOnLoad(gameObject);

            _audioSource = gameObject.AddComponent<AudioSource>();
            _audioSource.playOnAwake = false;
            _audioSource.loop = false;
            _audioSource.spatialBlend = 0f;
        }

        void OnDestroy()
        {
            if (Instance == this)
                Instance = null;
        }

        public void Play(EventFeedback ev)
        {
            if (string.IsNullOrEmpty(ev.SoundId))
                return;

            string key = BuildCooldownKey(ev);
            if (IsInCooldown(key))
                return;

            AudioClip clip = LoadClip(ev.SoundId);
            if (clip == null)
            {
                Debug.LogWarning($"[EventFeedbackAudioPlayer] AudioClip not found: {ev.SoundId}");
                return;
            }

            float volume = NormalizeVolume(ev.Volume);
            float pitch = NormalizePitch(ev.Pitch);

            _audioSource.pitch = pitch;
            _audioSource.PlayOneShot(clip, volume);

            _lastPlayedAt[key] = Time.unscaledTime;

            Debug.Log(
                $"[EventFeedbackAudioPlayer] play soundId={ev.SoundId}, type={ev.SoundType}, volume={volume:F2}, pitch={pitch:F2}"
            );
        }

        AudioClip LoadClip(string soundId)
        {
            if (_clipCache.TryGetValue(soundId, out AudioClip cached))
                return cached;

            AudioClip clip = Resources.Load<AudioClip>($"{ResourceRoot}/{soundId}");
            if (clip != null)
                _clipCache[soundId] = clip;

            return clip;
        }

        bool IsInCooldown(string key)
        {
            if (!_lastPlayedAt.TryGetValue(key, out float lastTime))
                return false;

            return Time.unscaledTime - lastTime < DefaultCooldownSec;
        }

        static string BuildCooldownKey(EventFeedback ev)
        {
            string eventType = string.IsNullOrEmpty(ev.EventType) ? "-" : ev.EventType;
            string target = string.IsNullOrEmpty(ev.Target) ? "-" : ev.Target;
            string soundId = string.IsNullOrEmpty(ev.SoundId) ? "-" : ev.SoundId;

            return $"{eventType}:{target}:{soundId}";
        }

        static float NormalizeVolume(float volume)
        {
            if (volume <= 0f)
                return DefaultVolume;

            return Mathf.Clamp01(volume);
        }

        static float NormalizePitch(float pitch)
        {
            if (pitch <= 0f)
                return DefaultPitch;

            return Mathf.Clamp(pitch, 0.25f, 3.0f);
        }
    }
}