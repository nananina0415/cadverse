using UnityEngine;

namespace Cadverse
{
    // Drag 모드 터치 중 화면에 표시되는 화살표.
    // 시작점은 터치 시작 시 raycast hit.point에 고정되고,
    // 끝점은 시작점이 위치한 평면(카메라 forward에 수직)과 현재 ray의 교차점.
    //
    // 사용 흐름:
    //   var arrow = DragArrow.Create();
    //   arrow.Show(hitPoint);                  // 터치 시작
    //   arrow.UpdateTip(currentRay);           // 터치 이동
    //   arrow.Hide();                          // 터치 종료
    //   arrow.DestroyArrow();                  // 정리
    public class DragArrow : MonoBehaviour
    {
        const float ShaftWidth = 0.004f;   // m
        const float HeadLength = 0.02f;    // m
        const float HeadWidth  = 0.012f;   // m

        LineRenderer _shaft;
        LineRenderer _head;
        Vector3      _start;
        Vector3      _planeNormal;   // 시작점이 놓인 평면의 법선 (= 카메라 forward at Show time)

        public static DragArrow Create()
        {
            var go    = new GameObject("DragArrow");
            var arrow = go.AddComponent<DragArrow>();
            arrow._shaft = MakeLine(go, "Shaft", ShaftWidth);
            arrow._head  = MakeLine(go, "Head",  HeadWidth);
            arrow.gameObject.SetActive(false);
            return arrow;
        }

        static LineRenderer MakeLine(GameObject parent, string name, float width)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent.transform, false);
            var lr = go.AddComponent<LineRenderer>();
            lr.useWorldSpace  = true;
            lr.positionCount  = 2;
            lr.startWidth     = width;
            lr.endWidth       = width;
            lr.material       = new Material(Shader.Find("Sprites/Default"));
            lr.startColor     = Color.yellow;
            lr.endColor       = Color.yellow;
            return lr;
        }

        public void Show(Vector3 start)
        {
            _start = start;
            // 시작 시점의 카메라 forward를 평면 법선으로 고정 — 이후 카메라가 움직여도 평면 안 따라감
            var cam = Camera.main;
            _planeNormal = cam != null ? cam.transform.forward : Vector3.forward;
            _shaft.SetPosition(0, _start);
            _shaft.SetPosition(1, _start);
            _head.SetPosition(0, _start);
            _head.SetPosition(1, _start);
            gameObject.SetActive(true);
        }

        public void UpdateTip(Ray currentRay)
        {
            // 시작점 평면(law: n·(p - start) = 0)과 ray의 교차
            float denom = Vector3.Dot(_planeNormal, currentRay.direction);
            if (Mathf.Abs(denom) < 1e-6f) return;   // ray가 평면과 평행

            float t = Vector3.Dot(_planeNormal, _start - currentRay.origin) / denom;
            if (t < 0f) return;                     // ray 뒤쪽이면 무시

            Vector3 tip = currentRay.origin + currentRay.direction * t;
            Vector3 dir = tip - _start;
            float   len = dir.magnitude;
            if (len < 1e-6f)
            {
                _shaft.SetPosition(1, _start);
                _head.SetPosition(0, _start);
                _head.SetPosition(1, _start);
                return;
            }

            // shaft는 start → (tip - 화살촉 길이)까지
            float shaftLen = Mathf.Max(0f, len - HeadLength);
            Vector3 shaftEnd = _start + dir.normalized * shaftLen;
            _shaft.SetPosition(0, _start);
            _shaft.SetPosition(1, shaftEnd);

            // head는 shaftEnd → tip (두꺼운 라인으로 표현)
            _head.SetPosition(0, shaftEnd);
            _head.SetPosition(1, tip);
        }

        public void Hide() => gameObject.SetActive(false);

        public void DestroyArrow()
        {
            if (this != null && gameObject != null)
                Destroy(gameObject);
        }
    }
}
